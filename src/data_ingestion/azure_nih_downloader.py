#!/usr/bin/env python3
"""
Download NIH Chest X-ray Dataset directly to Azure Blob Storage.
This script downloads images and uploads them directly to Azure without local storage.
"""

import os
import io
import json
import tarfile
import requests
import pandas as pd
from tqdm import tqdm
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from azure.storage.blob import BlobServiceClient, BlobClient
from azure.identity import DefaultAzureCredential, ClientSecretCredential
from azure.core.exceptions import ResourceExistsError

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AzureNIHDownloader:
    """Download NIH dataset directly to Azure Blob Storage."""
    
    def __init__(self, 
                 storage_account_name=None,
                 container_name="raw-images",
                 connection_string=None,
                 credential=None):
        """Initialize the Azure downloader.
        
        Args:
            storage_account_name: Azure Storage account name
            container_name: Blob container name
            connection_string: Azure Storage connection string (optional)
            credential: Azure credential object (optional)
        """
        self.container_name = container_name
        
        # Initialize Azure Blob Service Client
        if connection_string:
            self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        elif storage_account_name:
            account_url = f"https://{storage_account_name}.blob.core.windows.net"
            if credential:
                self.blob_service_client = BlobServiceClient(account_url, credential=credential)
            else:
                # Use default credential (managed identity, Azure CLI, etc.)
                self.blob_service_client = BlobServiceClient(account_url, credential=DefaultAzureCredential())
        else:
            raise ValueError("Must provide either connection_string or storage_account_name")
        
        # Get container client
        self.container_client = self.blob_service_client.get_container_client(container_name)
        
        # Ensure container exists
        try:
            self.container_client.create_container()
            logger.info(f"Created container: {container_name}")
        except ResourceExistsError:
            logger.info(f"Container already exists: {container_name}")
        
        # NIH dataset configuration
        self.base_url = "https://nihcc.box.com/shared/static/"
        self.image_files = [
            ("vfk49d74nhbxq3nqjg0900w5nvkorp5c", "images_001.tar.gz"),
            ("i28rlmbvmfjbl8p2n3ril0pptcmcu9d1", "images_002.tar.gz"),
            ("f1t00wrtdk94satdfb9olcolqx20z2jp", "images_003.tar.gz"),
            ("0aowwzs5lhjrceb3qp38l6aul94lu1zu", "images_004.tar.gz"),
            ("gqxdr411seyrzicdwfgh4tvf37x3pk0d", "images_005.tar.gz"),
            ("upyy3uifmk42q5cs5ece4f5vskhg8csj", "images_006.tar.gz"),
            ("psn8pwbdl4kcvfx2bjkqet1ndv96sg7u", "images_007.tar.gz"),
            ("t61lnuotlo9idt8qyv2zz8yrs67vfk89", "images_008.tar.gz"),
            ("k88cj55ug1lxwbpxenl6xbcgvj2psqkq", "images_009.tar.gz"),
            ("ixrbdthj8xwdfhz7t2e0j9kgvhnn5deo", "images_010.tar.gz"),
            ("e1ihjb73j8qy4dy6hvzl5ksir9zqhonk", "images_011.tar.gz"),
            ("rq6llqocl55h3tq9wso8uinhmg2n6kpq", "images_012.tar.gz")
        ]
        
        self.labels_url = "https://nihcc.app.box.com/index.php?rm=box_download_shared_file&shared_name=ChestXray-NIHCC&file_id=219760887468"
        self.labels_file = "Data_Entry_2017_v2020.csv"
    
    def upload_labels_to_azure(self):
        """Download and upload labels CSV to Azure Blob Storage."""
        logger.info("Checking if labels file exists in Azure...")
    
        # Check if labels file already exists in Azure
        labels_blob_client = self.container_client.get_blob_client(f"metadata/{self.labels_file}")
    
        try:
            if labels_blob_client.exists():
                logger.info(f"Labels file already exists in Azure: metadata/{self.labels_file}")
                # Download existing file and return its content
                blob_data = labels_blob_client.download_blob()
                return blob_data.readall()
            else:
                logger.info("Labels file doesn't exist. Attempting to download from NIH...")
        except Exception as e:
            logger.warning(f"Error checking if blob exists: {e}. Proceeding with download...")
        
        try:
            # Attempt to download labels from NIH
            logger.info("Downloading labels from NIH...")
            response = requests.get(self.labels_url, stream=True)
            response.raise_for_status()
            
            # Check if we got actual CSV content (not HTML error page)
            content_type = response.headers.get('content-type', '')
            if 'text/html' in content_type:
                logger.warning("Received HTML instead of CSV from NIH URL")
                raise requests.exceptions.RequestException("Got HTML instead of CSV")
            
            # Upload to Azure
            labels_blob_client.upload_blob(response.content, overwrite=True)
            logger.info(f"Labels downloaded and uploaded to Azure: metadata/{self.labels_file}")
            
            return response.content
            
        except Exception as e:
            logger.error(f"Failed to download labels from NIH: {e}")
            logger.error("Please manually upload the Data_Entry_2017_v2020.csv file to Azure Storage container metadata/ folder")
            raise 
        
    def download_and_extract_tar_to_azure(self, file_id, filename, max_workers=4):
        """Download tar file and extract images directly to Azure.
        
        Args:
            file_id: NIH file ID
            filename: Name of the tar file
            max_workers: Number of parallel upload threads
        """
        logger.info(f"Processing {filename}")
        url = f"{self.base_url}{file_id}"
        
        try:
            # Download tar file
            response = requests.get(url, stream=True)
            response.raise_for_status()
            
            # Get total size for progress bar
            total_size = int(response.headers.get('content-length', 0))
            
            # Download to memory buffer
            tar_buffer = io.BytesIO()
            
            with tqdm(desc=f"Downloading {filename}", total=total_size, unit='B', unit_scale=True) as pbar:
                for chunk in response.iter_content(chunk_size=8192):
                    tar_buffer.write(chunk)
                    pbar.update(len(chunk))
            
            tar_buffer.seek(0)
            
            # Extract and upload images
            self._extract_and_upload_images(tar_buffer, filename, max_workers)
            
        except Exception as e:
            logger.error(f"Failed to process {filename}: {e}")
            raise
    
    def _extract_and_upload_images(self, tar_buffer, tar_filename, max_workers=4):
        """Extract images from tar buffer and upload to Azure.
        
        Args:
            tar_buffer: BytesIO buffer containing tar file
            tar_filename: Name of the tar file for logging
            max_workers: Number of parallel upload threads
        """
        logger.info(f"Extracting and uploading images from {tar_filename}")
        
        try:
            with tarfile.open(fileobj=tar_buffer, mode='r:gz') as tar:
                # Get list of image files
                image_members = [member for member in tar.getmembers() if member.isfile() and member.name.lower().endswith('.png')]
                
                logger.info(f"Found {len(image_members)} images in {tar_filename}")
                
                # Upload images in parallel
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Submit all upload tasks
                    upload_tasks = []
                    for member in image_members:
                        task = executor.submit(self._upload_single_image, tar, member)
                        upload_tasks.append(task)
                    
                    # Process completed uploads with progress bar
                    successful_uploads = 0
                    failed_uploads = 0
                    
                    with tqdm(desc=f"Uploading from {tar_filename}", total=len(image_members)) as pbar:
                        for task in as_completed(upload_tasks):
                            try:
                                task.result()  # This will raise exception if upload failed
                                successful_uploads += 1
                            except Exception as e:
                                failed_uploads += 1
                                logger.warning(f"Upload failed: {e}")
                            finally:
                                pbar.update(1)
                    
                    logger.info(f"Completed {tar_filename}: {successful_uploads} successful, {failed_uploads} failed")
                    
        except Exception as e:
            logger.error(f"Failed to extract {tar_filename}: {e}")
            raise
    
    def _upload_single_image(self, tar, member):
        """Upload a single image to Azure Blob Storage.
        
        Args:
            tar: Open tarfile object
            member: TarInfo object for the image file
        """
        try:
            # Extract image data
            image_file = tar.extractfile(member)
            if image_file is None:
                raise ValueError(f"Could not extract {member.name}")
            
            image_data = image_file.read()
            
            # Create blob name (remove any directory path)
            blob_name = f"images/{os.path.basename(member.name)}"
            
            # Check if blob already exists
            blob_client = self.container_client.get_blob_client(blob_name)
            if blob_client.exists():
                logger.debug(f"Skipping existing blob: {blob_name}")
                return
            
            # Upload to Azure
            blob_client.upload_blob(image_data, overwrite=False)
            logger.debug(f"Uploaded: {blob_name}")
            
        except Exception as e:
            logger.error(f"Failed to upload {member.name}: {e}")
            raise
    
    def create_dataset_splits_in_azure(self, labels_data):
        """Create train/val/test splits and upload to Azure.
        
        Args:
            labels_data: Raw labels CSV data
        """
        logger.info("Creating dataset splits...")
        
        # Load labels into DataFrame
        df = pd.read_csv(io.StringIO(labels_data.decode('utf-8')))
        logger.info(f"Loaded {len(df)} image records")
        
        # Create binary labels for pathologies
        pathologies = [
            'Atelectasis', 'Consolidation', 'Infiltration', 'Pneumothorax', 'Edema',
            'Emphysema', 'Fibrosis', 'Effusion', 'Pneumonia', 'Pleural_Thickening',
            'Cardiomegaly', 'Nodule', 'Mass', 'Hernia'
        ]
        
        for pathology in pathologies:
            df[pathology] = df['Finding Labels'].str.contains(pathology, na=False).astype(int)
        
        # Split by patient to avoid data leakage
        unique_patients = df['Patient ID'].unique()
        n_patients = len(unique_patients)
        
        # 70% train, 15% val, 15% test
        train_patients = unique_patients[:int(0.7 * n_patients)]
        val_patients = unique_patients[int(0.7 * n_patients):int(0.85 * n_patients)]
        test_patients = unique_patients[int(0.85 * n_patients):]
        
        # Create splits
        train_df = df[df['Patient ID'].isin(train_patients)]
        val_df = df[df['Patient ID'].isin(val_patients)]
        test_df = df[df['Patient ID'].isin(test_patients)]
        
        # Select columns for ML training
        columns_to_keep = ['Image Index'] + pathologies
        
        # Upload splits to Azure
        splits = {
            'train.csv': train_df[columns_to_keep],
            'val.csv': val_df[columns_to_keep],
            'test.csv': test_df[columns_to_keep]
        }
        
        for filename, data in splits.items():
            csv_buffer = io.StringIO()
            data.to_csv(csv_buffer, index=False)
            csv_data = csv_buffer.getvalue().encode('utf-8')
            
            blob_client = self.container_client.get_blob_client(f"metadata/{filename}")
            blob_client.upload_blob(csv_data, overwrite=True)
            logger.info(f"Uploaded split: metadata/{filename}")
        
        logger.info(f"Dataset splits created:")
        logger.info(f"- Training: {len(train_df)} images")
        logger.info(f"- Validation: {len(val_df)} images")
        logger.info(f"- Testing: {len(test_df)} images")
        
        # Create and upload dataset info
        dataset_info = {
            "total_images": len(df),
            "train_images": len(train_df),
            "val_images": len(val_df),
            "test_images": len(test_df),
            "pathologies": pathologies,
            "pathology_counts": df[pathologies].sum().to_dict()
        }
        
        info_blob = self.container_client.get_blob_client("metadata/dataset_info.json")
        info_blob.upload_blob(json.dumps(dataset_info, indent=2), overwrite=True)
        logger.info("Uploaded dataset info: metadata/dataset_info.json")
    
    def download_complete_dataset(self, max_workers=2):
        """Download the complete NIH dataset to Azure Blob Storage.
        
        Args:
            max_workers: Number of parallel tar file downloads
        """
        logger.info("Starting NIH Chest X-ray dataset download to Azure")
        
        # Upload labels first
        labels_data = self.upload_labels_to_azure()
        
        # Create dataset splits
        self.create_dataset_splits_in_azure(labels_data)
        
        # Download and upload images
        logger.info("Starting image download and upload...")
        
        for file_id, filename in self.image_files:
            try:
                self.download_and_extract_tar_to_azure(file_id, filename, max_workers=4)
            except Exception as e:
                logger.error(f"Failed to process {filename}: {e}")
                continue
        
        logger.info("Dataset download to Azure complete!")
        logger.info(f"Images stored in container: {self.container_name}")
    
    def download_sample_dataset(self, max_files=2):
        """Download just a sample of the dataset for testing.
        
        Args:
            max_files: Maximum number of tar files to download
        """
        logger.info(f"Downloading sample dataset ({max_files} files) to Azure")
        
        # Upload labels
        labels_data = self.upload_labels_to_azure()
        
        # Create dataset splits
        self.create_dataset_splits_in_azure(labels_data)
        
        # Download only the first few tar files
        for file_id, filename in self.image_files[:max_files]:
            try:
                self.download_and_extract_tar_to_azure(file_id, filename, max_workers=4)
            except Exception as e:
                logger.error(f"Failed to process {filename}: {e}")
                continue
        
        logger.info("Sample dataset download to Azure complete!")


def main():
    """Main function to run the Azure downloader."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Download NIH dataset to Azure Blob Storage')
    parser.add_argument('--storage-account', type=str, help='Azure Storage account name')
    parser.add_argument('--container', type=str, default='raw-images', help='Container name')
    parser.add_argument('--connection-string', type=str, help='Azure Storage connection string')
    parser.add_argument('--tenant-id', type=str, help='Azure tenant ID for service principal auth')
    parser.add_argument('--client-id', type=str, help='Azure client ID for service principal auth')
    parser.add_argument('--client-secret', type=str, help='Azure client secret for service principal auth')
    parser.add_argument('--sample-only', action='store_true', help='Download only a sample (2 tar files)')
    parser.add_argument('--max-workers', type=int, default=2, help='Max parallel downloads')
    
    args = parser.parse_args()
    
    # Set up credential
    credential = None
    connection_string = args.connection_string or os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
    storage_account = args.storage_account or os.environ.get('AZURE_STORAGE_ACCOUNT_NAME')
    
    if args.tenant_id and args.client_id and args.client_secret:
        credential = ClientSecretCredential(
            tenant_id=args.tenant_id,
            client_id=args.client_id,
            client_secret=args.client_secret
        )
    
    # Create downloader
    downloader = AzureNIHDownloader(
        storage_account_name=storage_account,
        container_name=args.container,
        connection_string=connection_string,
        credential=credential
    )
    
    # Download dataset
    if args.sample_only:
        downloader.download_sample_dataset(max_files=2)
    else:
        downloader.download_complete_dataset(max_workers=args.max_workers)


if __name__ == "__main__":
    main()