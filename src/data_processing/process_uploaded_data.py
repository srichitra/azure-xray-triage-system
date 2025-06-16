#!/usr/bin/env python3
"""
Process manually uploaded NIH dataset in Azure Storage.
This script organizes and validates the uploaded data.
"""

import os
import json
import logging
import pandas as pd
import numpy as np
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DataProcessor:
    """Process uploaded NIH dataset in Azure Storage."""
    
    def __init__(self, 
                 storage_account_name=None,
                 container_name="raw-images",
                 connection_string=None):
        """Initialize the data processor."""
        self.container_name = container_name
        
        # Initialize Azure Blob Service Client
        if connection_string:
            self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        elif storage_account_name:
            account_url = f"https://{storage_account_name}.blob.core.windows.net"
            self.blob_service_client = BlobServiceClient(account_url, credential=DefaultAzureCredential())
        else:
            raise ValueError("Must provide either connection_string or storage_account_name")
        
        self.container_client = self.blob_service_client.get_container_client(container_name)
    
    def list_uploaded_files(self):
        """List all uploaded files and organize by type."""
        logger.info("Analyzing uploaded files...")
        
        files = {
            'images': [],
            'csv_files': [],
            'tar_files': [],
            'other': []
        }
        
        total_size = 0
        
        for blob in self.container_client.list_blobs():
            blob_size = blob.size
            total_size += blob_size
            
            if blob.name.endswith('.png'):
                files['images'].append(blob.name)
            elif blob.name.endswith('.csv'):
                files['csv_files'].append(blob.name)
            elif blob.name.endswith('.tar.gz'):
                files['tar_files'].append(blob.name)
            else:
                files['other'].append(blob.name)
        
        # Print summary
        logger.info(f"File inventory:")
        logger.info(f"- Images (.png): {len(files['images'])}")
        logger.info(f"- CSV files: {len(files['csv_files'])}")
        logger.info(f"- TAR files: {len(files['tar_files'])}")
        logger.info(f"- Other files: {len(files['other'])}")
        logger.info(f"- Total storage used: {total_size / (1024**3):.2f} GB")
        
        return files
    
    def process_csv_labels(self):
        """Process the CSV labels file and create train/val/test splits."""
        logger.info("Processing CSV labels...")
        
        # Find the CSV file
        csv_files = []
        for blob in self.container_client.list_blobs():
            if blob.name.endswith('.csv') and 'Data_Entry' in blob.name:
                csv_files.append(blob.name)
        
        if not csv_files:
            logger.error("No Data_Entry CSV file found!")
            return False
        
        csv_file = csv_files[0]
        logger.info(f"Processing CSV file: {csv_file}")
        
        # Download CSV content
        blob_client = self.container_client.get_blob_client(csv_file)
        csv_content = blob_client.download_blob().readall().decode('utf-8')
        
        # Load into DataFrame
        df = pd.read_csv(pd.io.common.StringIO(csv_content))
        logger.info(f"Loaded {len(df)} records from CSV")
        
        # Create binary labels for pathologies
        pathologies = [
            'Atelectasis', 'Consolidation', 'Infiltration', 'Pneumothorax', 'Edema',
            'Emphysema', 'Fibrosis', 'Effusion', 'Pneumonia', 'Pleural_Thickening',
            'Cardiomegaly', 'Nodule', 'Mass', 'Hernia'
        ]
        
        # Handle NaN values
        df['Finding Labels'] = df['Finding Labels'].fillna('No Finding')
        
        # Create binary columns
        for pathology in pathologies:
            df[pathology] = df['Finding Labels'].str.contains(pathology, na=False).astype(int)
        
        # Filter to only include images that actually exist in storage
        existing_images = set()
        for blob in self.container_client.list_blobs():
            if blob.name.endswith('.png'):
                existing_images.add(os.path.basename(blob.name))
        
        # Filter DataFrame to only include existing images
        df_filtered = df[df['Image Index'].isin(existing_images)]
        logger.info(f"Filtered to {len(df_filtered)} records with existing images")
        
        # Split by patient to avoid data leakage
        if 'Patient ID' in df_filtered.columns:
            unique_patients = df_filtered['Patient ID'].unique()
            n_patients = len(unique_patients)
            
            np.random.seed(42)
            shuffled_patients = np.random.permutation(unique_patients)
            
            train_patients = shuffled_patients[:int(0.7 * n_patients)]
            val_patients = shuffled_patients[int(0.7 * n_patients):int(0.85 * n_patients)]
            test_patients = shuffled_patients[int(0.85 * n_patients):]
            
            train_df = df_filtered[df_filtered['Patient ID'].isin(train_patients)]
            val_df = df_filtered[df_filtered['Patient ID'].isin(val_patients)]
            test_df = df_filtered[df_filtered['Patient ID'].isin(test_patients)]
        else:
            # Random split if no Patient ID
            df_shuffled = df_filtered.sample(frac=1, random_state=42).reset_index(drop=True)
            n_samples = len(df_shuffled)
            
            train_size = int(0.7 * n_samples)
            val_size = int(0.15 * n_samples)
            
            train_df = df_shuffled[:train_size]
            val_df = df_shuffled[train_size:train_size + val_size]
            test_df = df_shuffled[train_size + val_size:]
        
        # Save splits
        columns_to_keep = ['Image Index'] + pathologies
        
        splits = {
            'train.csv': train_df[columns_to_keep],
            'val.csv': val_df[columns_to_keep],
            'test.csv': test_df[columns_to_keep]
        }
        
        for filename, data in splits.items():
            csv_content = data.to_csv(index=False)
            blob_client = self.container_client.get_blob_client(f"metadata/{filename}")
            blob_client.upload_blob(csv_content.encode('utf-8'), overwrite=True)
            logger.info(f"Uploaded {filename}: {len(data)} samples")
        
        # Create dataset info
        pathology_counts = {}
        for pathology in pathologies:
            pathology_counts[pathology] = int(df_filtered[pathology].sum())
        
        dataset_info = {
            "total_images": len(df_filtered),
            "train_images": len(train_df),
            "val_images": len(val_df),
            "test_images": len(test_df),
            "pathologies": pathologies,
            "pathology_counts": pathology_counts,
            "source": "NIH Chest X-ray Dataset (manually uploaded)"
        }
        
        # Upload dataset info
        info_blob = self.container_client.get_blob_client("metadata/dataset_info.json")
        info_blob.upload_blob(json.dumps(dataset_info, indent=2), overwrite=True)
        
        logger.info("Dataset processing completed!")
        logger.info(f"Train: {len(train_df)}, Val: {len(val_df)}, Test: {len(test_df)}")
        
        return True
    
    def verify_dataset(self):
        """Verify the dataset is ready for training."""
        logger.info("Verifying dataset...")
        
        required_files = [
            'metadata/train.csv',
            'metadata/val.csv', 
            'metadata/test.csv',
            'metadata/dataset_info.json'
        ]
        
        all_good = True
        for file_path in required_files:
            try:
                blob_client = self.container_client.get_blob_client(file_path)
                if blob_client.exists():
                    logger.info(f"✓ Found {file_path}")
                else:
                    logger.error(f"✗ Missing {file_path}")
                    all_good = False
            except Exception as e:
                logger.error(f"✗ Error checking {file_path}: {e}")
                all_good = False
        
        if all_good:
            logger.info("🎉 Dataset verification passed! Ready for training.")
        else:
            logger.error("❌ Dataset verification failed!")
        
        return all_good


def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Process uploaded NIH dataset')
    parser.add_argument('--storage-account', type=str, help='Azure Storage account name')
    parser.add_argument('--container', type=str, default='raw-images', help='Container name')
    parser.add_argument('--connection-string', type=str, help='Azure Storage connection string')
    
    args = parser.parse_args()
    
    connection_string = args.connection_string or os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
    storage_account = args.storage_account or os.environ.get('AZURE_STORAGE_ACCOUNT_NAME')
    
    processor = DataProcessor(
        storage_account_name=storage_account,
        container_name=args.container,
        connection_string=connection_string
    )
    
    # Process the data
    processor.list_uploaded_files()
    processor.process_csv_labels()
    processor.verify_dataset()


if __name__ == "__main__":
    main()