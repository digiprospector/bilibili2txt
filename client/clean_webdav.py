import sys
from pathlib import Path
import requests
import xml.etree.ElementTree as ET

# Add project directories to sys.path
SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))

from dp_logging import setup_logger
from config import config
from webdav import delete_from_webdav_requests

# Setup logger
logger = setup_logger(Path(__file__).stem, log_dir=SCRIPT_DIR.parent / "logs")

def list_webdav_files(webdav_url, username, password):
    """
    Lists all files in the given WebDAV directory using PROPFIND.
    Returns a list of full URLs for each file.
    """
    logger.info(f"Listing files from WebDAV server: {webdav_url}")
    try:
        response = requests.request(
            "PROPFIND",
            webdav_url,
            auth=(username, password),
            headers={"Depth": "1"},
            timeout=30
        )
        response.raise_for_status()

        # Namespace for DAV XML elements
        ns = {'d': 'DAV:'}
        root = ET.fromstring(response.content)
        
        base_url = webdav_url.rstrip('/')
        files = []
        for response_elem in root.findall('d:response', ns):
            href = response_elem.find('d:href', ns).text
            # Exclude the directory itself (href ends with /)
            if not href.endswith('/'):
                # Construct full URL
                file_url = f"{base_url}/{href.split('/')[-1]}"
                files.append(file_url)
        
        logger.info(f"Found {len(files)} files on WebDAV server.")
        return files

    except requests.exceptions.RequestException as e:
        logger.error(f"Error listing files from WebDAV: {e}")
        return []
    except Exception as e:
        logger.error(f"An unexpected error occurred while listing files: {e}")
        return []

def clean_webdav():
    """
    Deletes all files from the WebDAV server specified in the config.
    """
    webdav_url = config.get('webdav_url')
    username = config.get('webdav_username')
    password = config.get('webdav_password')

    if not all([webdav_url, username, password]):
        logger.error("WebDAV configuration (webdav_url, webdav_username, webdav_password) is missing in config.py.")
        return

    files_to_delete = list_webdav_files(webdav_url, username, password)

    for file_url in files_to_delete:
        logger.info(f"Deleting file: {file_url}")
        delete_from_webdav_requests(url=file_url, username=username, password=password, logger=logger)

if __name__ == "__main__":
    clean_webdav()
    logger.info("WebDAV cleanup process finished.")