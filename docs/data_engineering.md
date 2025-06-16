# Data Engineering

## NIH Chest X-ray Dataset

The NIH Chest X-ray Dataset is a collection of chest X-ray images provided by the National Institutes of Health Clinical Center. It contains 112,120 X-ray images from 30,805 unique patients, with 14 different disease labels extracted from radiology reports using natural language processing.

### Dataset Details

- **Size**: ~45GB
- **Images**: 112,120 X-ray images in PNG format
- **Labels**: 14 disease classes including Atelectasis, Consolidation, Infiltration, Pneumothorax, Edema, Emphysema, Fibrosis, Effusion, Pneumonia, Pleural thickening, Cardiomegaly, Nodule, Mass, and Hernia
- **Format**: PNG images with corresponding metadata
- **Source**: [NIH Clinical Center](https://nihcc.app.box.com/v/ChestXray-NIHCC)

### Data Processing Pipeline

1. **Download**: Images are downloaded from the NIH source
2. **Validation**: Each image is validated for quality and format
3. **Anonymization**: PHI is removed from DICOM headers
4. **Conversion**: DICOM files are converted to normalized PNG format
5. **Upload**: Processed images are stored in Azure Blob Storage
6. **Indexing**: Image metadata is stored in Azure SQL Database

### Storage Structure

- **Raw Container**: Original downloaded images
- **Processed Container**: Anonymized and normalized images
- **Model Data Container**: Training, validation, and test datasets

### Access Patterns

- Azure Blob Storage is used for high-throughput image storage
- Azure Data Lake Analytics is used for processing large batches
- RBAC is implemented for secure access control