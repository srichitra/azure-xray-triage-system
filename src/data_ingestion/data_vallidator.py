# src/data/data_validator.py
import os
import logging
import pydicom
import pandas as pd
from collections import Counter

logger = logging.getLogger(__name__)

class DataValidator:
    """Validate X-ray DICOM data for quality and consistency."""
    
    def __init__(self):
        """Initialize the data validator."""
        pass
    
    def validate_dicom_file(self, file_path):
        """Validate a single DICOM file.
        
        Args:
            file_path: Path to the DICOM file
            
        Returns:
            Dictionary with validation results
        """
        validation_results = {
            "file_path": file_path,
            "valid": False,
            "issues": []
        }
        
        try:
            # Attempt to read the DICOM file
            dicom_data = pydicom.dcmread(file_path)
            
            # Check for required fields
            required_fields = [
                'StudyInstanceUID', 'SeriesInstanceUID', 'SOPInstanceUID',
                'Modality', 'PixelData'
            ]
            
            for field in required_fields:
                if not hasattr(dicom_data, field):
                    validation_results["issues"].append(f"Missing required field: {field}")
            
            # Check for X-ray modality
            if hasattr(dicom_data, 'Modality') and dicom_data.Modality != 'DX':
                validation_results["issues"].append(f"Not a chest X-ray. Modality: {dicom_data.Modality}")
            
            # Check for pixel data
            if hasattr(dicom_data, 'PixelData'):
                # Check image dimensions
                if dicom_data.pixel_array.size == 0:
                    validation_results["issues"].append("Empty pixel data")
                    
                # Check for reasonable image dimensions
                rows = getattr(dicom_data, 'Rows', 0)
                columns = getattr(dicom_data, 'Columns', 0)
                if rows < 100 or columns < 100:
                    validation_results["issues"].append(f"Image too small: {rows}x{columns}")
            else:
                validation_results["issues"].append("No pixel data found")
            
            # Set valid flag if no issues found
            if not validation_results["issues"]:
                validation_results["valid"] = True
                
        except Exception as e:
            validation_results["issues"].append(f"Error reading DICOM file: {str(e)}")
        
        return validation_results
    
    def validate_dataset(self, directory):
        """Validate a directory of DICOM files.
        
        Args:
            directory: Directory containing DICOM files
            
        Returns:
            DataFrame with validation results
        """
        results = []
        
        # Walk through directory
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith('.dcm'):
                    file_path = os.path.join(root, file)
                    result = self.validate_dicom_file(file_path)
                    results.append(result)
        
        # Convert to DataFrame
        df = pd.DataFrame(results)
        
        # Print summary
        total = len(df)
        valid = df['valid'].sum()
        print(f"Validated {total} files. {valid} valid, {total - valid} invalid.")
        
        # Summarize issues
        if not df.empty and 'issues' in df.columns:
            all_issues = [issue for sublist in df['issues'] for issue in sublist]
            issue_counts = Counter(all_issues)
            print("\nIssue summary:")
            for issue, count in issue_counts.most_common():
                print(f"- {issue}: {count} files")
        
        return df