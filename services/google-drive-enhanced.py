from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from typing import List, Dict, Set, Optional, Tuple, Any
import logging
import json
import os
from datetime import datetime
from services.db_config import db, DriveFile
from config.settings import GOOGLE_CREDENTIALS_PATH, DRIVE_SCOPES

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DriveAPIError(Exception):
    """Custom exception for Drive API related errors."""
    pass

def authenticate_drive_api() -> Any:
    """
    Authenticates and returns the Google Drive API service using a service account.

    Returns:
        googleapiclient.discovery.Resource: Authenticated Drive API service

    Raises:
        DriveAPIError: If authentication fails
    """
    try:
        if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
            raise DriveAPIError("Service account credentials file not found")

        credentials = service_account.Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS_PATH, scopes=DRIVE_SCOPES)
        service = build('drive', 'v3', credentials=credentials)
        logger.info("Successfully authenticated with Google Drive API")
        return service

    except Exception as e:
        logger.error(f"Failed to authenticate with service account: {str(e)}")
        raise DriveAPIError(f"Authentication failed: {str(e)}")

def get_folder_contents(
    service: Any,
    folder_id: str,
    fields: str = "id, name, mimeType, createdTime, size, webViewLink, description"
) -> List[Dict]:
    """
    Fetches metadata of files and folders within the specified Google Drive folder.

    Args:
        service: Authenticated Drive API service
        folder_id: ID of the folder to fetch contents from
        fields: Comma-separated list of fields to retrieve

    Returns:
        List of dictionaries containing file/folder metadata

    Raises:
        DriveAPIError: If API request fails
    """
    try:
        query = f"'{folder_id}' in parents and trashed = false"
        items = []
        page_token = None

        while True:
            try:
                response = service.files().list(
                    q=query,
                    fields=f"nextPageToken, files({fields})",
                    pageToken=page_token,
                    pageSize=1000
                ).execute()

                items.extend(response.get('files', []))
                page_token = response.get('nextPageToken')

                if not page_token:
                    break

            except HttpError as e:
                if e.resp.status == 404:
                    logger.error(f"Folder {folder_id} not found")
                    raise DriveAPIError(f"Folder not found: {folder_id}")
                raise

        logger.info(f"Retrieved {len(items)} items from folder {folder_id}")
        return items

    except Exception as e:
        logger.error(f"Error fetching folder contents: {str(e)}")
        raise DriveAPIError(f"Failed to fetch folder contents: {str(e)}")

def parse_tags_and_notebooklm(description: Optional[str]) -> Tuple[List[str], Optional[str]]:
    """
    Parses tags and NotebookLM link from the description field.

    Args:
        description: File/folder description text

    Returns:
        Tuple containing:
            - List of tags (strings starting with #)
            - NotebookLM link if present, None otherwise
    """
    if not description:
        return [], None

    tags = []
    notebooklm_link = None

    try:
        items = [item.strip() for item in description.split(',')]

        tags = [item for item in items if item.startswith('#')]
        notebooklm_links = [item for item in items
                           if item.startswith('http') and 'notebooklm' in item.lower()]

        notebooklm_link = notebooklm_links[0] if notebooklm_links else None

        return tags, notebooklm_link

    except Exception as e:
        logger.warning(f"Error parsing description: {str(e)}")
        return [], None

def build_folder_tree(
    service: Any,
    folder_id: str,
    visited: Optional[Set[str]] = None,
    max_depth: int = 10
) -> List[Dict]:
    """
    Recursively builds a tree structure of folders and files.

    Args:
        service: Authenticated Drive API service
        folder_id: ID of the root folder
        visited: Set of visited folder IDs to prevent cycles
        max_depth: Maximum recursion depth

    Returns:
        List of dictionaries representing the folder tree structure

    Raises:
        DriveAPIError: If building the tree fails
    """
    if visited is None:
        visited = set()

    if len(visited) >= max_depth:
        logger.warning(f"Max depth {max_depth} reached, stopping recursion")
        return []

    visited.add(folder_id)
    tree = []

    try:
        items = get_folder_contents(service, folder_id)

        for item in items:
            tags, notebooklm_link = parse_tags_and_notebooklm(item.get('description', ''))

            structured_item = {
                'id': item.get('id'),
                'name': item.get('name'),
                'type': 'Folder' if item.get('mimeType') == 'application/vnd.google-apps.folder' else 'File',
                'webViewLink': item.get('webViewLink'),
                'created_time': item.get('createdTime'),
                'size': int(item.get('size', 0)) if item.get('size') else None,
                'tags': tags,
                'NotebookLM': notebooklm_link,
                'last_synced': datetime.utcnow().isoformat()
            }

            if (item.get('mimeType') == 'application/vnd.google-apps.folder' and
                item.get('id') not in visited):
                structured_item['children'] = build_folder_tree(
                    service, item.get('id'), visited, max_depth)

            tree.append(structured_item)

        return tree

    except Exception as e:
        logger.error(f"Error building folder tree: {str(e)}")
        raise DriveAPIError(f"Failed to build folder tree: {str(e)}")

def save_to_database(
    items: List[Dict],
    parent_path: str = '',
    batch_size: int = 100
) -> None:
    """
    Saves the folder tree to the database with batch processing.

    Args:
        items: List of items to save
        parent_path: Path of parent folder
        batch_size: Number of items to commit in each batch

    Raises:
        Exception: If database operations fail
    """
    try:
        batch_count = 0

        for item in items:
            current_path = f"{parent_path}/{item['name']}" if parent_path else item['name']

            try:
                drive_file = DriveFile.query.get(item['id'])
                if not drive_file:
                    drive_file = DriveFile(id=item['id'])

                drive_file.name = item['name']
                drive_file.file_path = current_path
                drive_file.url = item.get('webViewLink')
                drive_file.tags = ','.join(item.get('tags', []))
                drive_file.notebooklm = item.get('NotebookLM')
                drive_file.is_folder = item['type'] == 'Folder'
                drive_file.last_synced = datetime.utcnow()

                db.session.add(drive_file)
                batch_count += 1

                if batch_count >= batch_size:
                    db.session.commit()
                    batch_count = 0

                if 'children' in item:
                    save_to_database(item['children'], current_path, batch_size)

            except Exception as e:
                logger.error(f"Error saving item {item['id']}: {str(e)}")
                db.session.rollback()
                raise

        if batch_count > 0:
            db.session.commit()

    except Exception as e:
        logger.error(f"Database operation failed: {str(e)}")
        db.session.rollback()
        raise

def sync_drive_folder(folder_id: str) -> Dict:
    """
    Main function to sync a Google Drive folder with the database.

    Args:
        folder_id: ID of the root folder to sync

    Returns:
        Dictionary containing sync statistics

    Raises:
        DriveAPIError: If sync fails
    """
    try:
        start_time = datetime.utcnow()
        service = authenticate_drive_api()

        logger.info(f"Starting sync for folder {folder_id}")
        folder_tree = build_folder_tree(service, folder_id)

        save_to_database(folder_tree)

        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()

        stats = {
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'duration_seconds': duration,
            'folders_processed': sum(1 for item in folder_tree if item['type'] == 'Folder'),
            'files_processed': sum(1 for item in folder_tree if item['type'] == 'File')
        }

        logger.info(f"Sync completed successfully: {json.dumps(stats, indent=2)}")
        return stats

    except Exception as e:
        logger.error(f"Sync failed: {str(e)}")
        raise DriveAPIError(f"Sync failed: {str(e)}")
