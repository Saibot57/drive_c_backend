from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime
import json
import logging
from services.db_config import db, DriveFile
from config.settings import GOOGLE_CREDENTIALS_PATH, DRIVE_SCOPES

# Set up logging
logger = logging.getLogger(__name__)

def authenticate_drive_api():
    """
    Authenticates and returns the Google Drive API service using a service account.

    Returns:
        google.oauth2.credentials.Credentials: Authenticated Drive API service

    Raises:
        Exception: If authentication fails
    """
    try:
        logger.info("Authenticating with Google Drive API")
        credentials = service_account.Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS_PATH, scopes=DRIVE_SCOPES)
        service = build('drive', 'v3', credentials=credentials)
        logger.info("Successfully authenticated with Google Drive API")
        return service
    except Exception as e:
        logger.error(f"Error authenticating with service account: {e}")
        raise

def get_folder_contents(service, folder_id):
    """
    Fetches metadata of files and folders within the specified Google Drive folder.

    Args:
        service: Authenticated Drive API service
        folder_id: ID of the folder to fetch contents from

    Returns:
        list: List of file/folder metadata items

    Raises:
        HttpError: If the API request fails
    """
    try:
        logger.info(f"Fetching contents of folder: {folder_id}")
        query = f"'{folder_id}' in parents and trashed = false"
        items = []
        page_token = None

        while True:
            try:
                response = service.files().list(
                    q=query,
                    fields="nextPageToken, files(id, name, mimeType, createdTime, size, webViewLink, description)",
                    pageToken=page_token,
                    pageSize=1000,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True
                ).execute()

                current_items = response.get('files', [])
                items.extend(current_items)
                logger.debug(f"Fetched {len(current_items)} items from folder")

                page_token = response.get('nextPageToken')
                if not page_token:
                    break

            except HttpError as e:
                if e.resp.status == 404:
                    logger.error(f"Folder {folder_id} not found")
                    raise
                logger.error(f"HTTP error while fetching folder contents: {e}")
                raise

        logger.info(f"Successfully fetched {len(items)} items from folder {folder_id}")
        return items

    except Exception as e:
        logger.error(f"Error fetching folder contents: {e}")
        raise

def parse_tags_and_notebooklm(description):
    """
    Parses tags and NotebookLM link from the description field.

    Args:
        description: File/folder description text

    Returns:
        tuple: (list of tags, NotebookLM link or None)
    """
    if not description:
        return [], None

    try:
        tags = []
        notebooklm_link = None

        items = [item.strip() for item in description.split(',')]

        # Extract tags and NotebookLM link
        for item in items:
            if item.startswith('#'):
                tags.append(item)
            elif item.startswith('http') and 'notebooklm' in item.lower():
                notebooklm_link = item

        return tags, notebooklm_link

    except Exception as e:
        logger.warning(f"Error parsing description: {e}")
        return [], None

def build_folder_tree(service, folder_id, visited=None, max_depth=10):
    """
    Recursively builds a tree structure of folders and files.

    Args:
        service: Authenticated Drive API service
        folder_id: ID of the root folder
        visited: Set of visited folder IDs (for cycle detection)
        max_depth: Maximum recursion depth

    Returns:
        list: Tree structure of folders and files

    Raises:
        Exception: If building the tree fails
    """
    if visited is None:
        visited = set()

    if len(visited) >= max_depth:
        logger.warning(f"Max depth {max_depth} reached, stopping recursion")
        return []

    try:
        visited.add(folder_id)
        items = get_folder_contents(service, folder_id)
        tree = []

        for item in items:
            try:
                tags, notebooklm_link = parse_tags_and_notebooklm(item.get('description', ''))

                structured_item = {
                    'id': item.get('id'),
                    'name': item.get('name'),
                    'type': 'Folder' if item.get('mimeType') == 'application/vnd.google-apps.folder' else 'File',
                    'webViewLink': item.get('webViewLink'),
                    'createdTime': item.get('createdTime'),
                    'size': int(item.get('size', 0)) if item.get('size') else None,
                    'tags': tags,
                    'NotebookLM': notebooklm_link
                }

                if (item.get('mimeType') == 'application/vnd.google-apps.folder' and
                    item.get('id') not in visited):
                    structured_item['children'] = build_folder_tree(
                        service, item.get('id'), visited, max_depth)

                tree.append(structured_item)

            except Exception as e:
                logger.error(f"Error processing item {item.get('name', 'unknown')}: {e}")
                continue

        return tree

    except Exception as e:
        logger.error(f"Error building folder tree: {e}")
        raise

def save_to_database(items, user_id, parent_path=''):
    """
    Saves the folder tree to the database with improved error handling.
    Args:
        items: List of items to save
        user_id: User ID to associate with the files
        parent_path: Path of parent folder
    """
    try:
        for item in items:
            try:
                current_path = f"{parent_path}/{item['name']}" if parent_path else item['name']

                # Create the record
                drive_file = DriveFile(
                    id=item['id'],
                    name=item['name'],
                    file_path=current_path,
                    url=item.get('webViewLink'),
                    tags=','.join(item.get('tags', [])),
                    notebooklm=item.get('NotebookLM'),
                    is_folder=item['type'] == 'Folder',
                    user_id=user_id  # Set user ID for each item
                )

                # Handle created time
                if 'createdTime' in item:
                    try:
                        drive_file.created_time = datetime.strptime(
                            item['createdTime'],
                            "%Y-%m-%dT%H:%M:%S.%fZ"
                        )
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Failed to parse created_time for {item['name']}: {e}")

                db.session.add(drive_file)

                # Process children if they exist
                if 'children' in item:
                    save_to_database(item['children'], user_id, current_path)

            except Exception as e:
                logger.error(f"Error processing item {item.get('name', 'unknown')}: {str(e)}")
                raise

    except Exception as e:
        logger.error(f"Error in save_to_database: {str(e)}")
        raise

def save_to_database_with_session(items, user_id, session, parent_path=''):
    """
    Saves the folder tree to the database using the provided session.
    Args:
        items: List of items to save
        user_id: User ID to associate with the files
        session: SQLAlchemy session to use
        parent_path: Path of parent folder
    """
    try:
        for item in items:
            try:
                current_path = f"{parent_path}/{item['name']}" if parent_path else item['name']

                # Create the record
                drive_file = DriveFile(
                    id=item['id'],
                    name=item['name'],
                    file_path=current_path,
                    url=item.get('webViewLink'),
                    tags=','.join(item.get('tags', [])),
                    notebooklm=item.get('NotebookLM'),
                    is_folder=item['type'] == 'Folder',
                    user_id=user_id  # Set user ID for each item
                )

                # Handle created time
                if 'createdTime' in item:
                    try:
                        drive_file.created_time = datetime.strptime(
                            item['createdTime'],
                            "%Y-%m-%dT%H:%M:%S.%fZ"
                        )
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Failed to parse created_time for {item['name']}: {e}")

                session.add(drive_file)

                # Process children if they exist
                if 'children' in item:
                    save_to_database_with_session(item['children'], user_id, session, current_path)

            except Exception as e:
                logger.error(f"Error processing item {item.get('name', 'unknown')}: {str(e)}")
                raise

    except Exception as e:
        logger.error(f"Error in save_to_database_with_session: {str(e)}")
        raise