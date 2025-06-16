#!/bin/bash
# Azure Setup and NIH Dataset Download Script
# This script sets up Azure infrastructure and downloads the NIH dataset directly to Azure Storage

set -e  # Exit on any error

# Configuration
RESOURCE_GROUP="xray-triage-rg"
LOCATION="eastus"
STORAGE_ACCOUNT="xraytriagework2213067047"
CONTAINER_RAW="raw-images"
CONTAINER_PROCESSED="processed-images"
CONTAINER_MODELS="model-data"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if Azure CLI is installed
check_azure_cli() {
    if ! command -v az &> /dev/null; then
        print_error "Azure CLI is not installed. Please install it first:"
        echo "https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
        exit 1
    fi
    print_status "Azure CLI is installed"
}

# Function to login to Azure
azure_login() {
    print_status "Checking Azure login status..."
    if ! az account show &> /dev/null; then
        print_status "Please login to Azure"
        az login
    else
        print_status "Already logged in to Azure"
    fi
    
    # Show current subscription
    SUBSCRIPTION=$(az account show --query name -o tsv)
    print_status "Using subscription: $SUBSCRIPTION"
}

# Function to create resource group
create_resource_group() {
    print_status "Creating resource group: $RESOURCE_GROUP"
    
    if az group show --name $RESOURCE_GROUP &> /dev/null; then
        print_warning "Resource group $RESOURCE_GROUP already exists"
    else
        az group create --name $RESOURCE_GROUP --location $LOCATION
        print_status "Resource group created successfully"
    fi
}

# Function to create storage account
create_storage_account() {
    print_status "Creating storage account: $STORAGE_ACCOUNT"
    
    # Check if storage account exists
    if az storage account show --name $STORAGE_ACCOUNT --resource-group $RESOURCE_GROUP &> /dev/null; then
        print_warning "Storage account $STORAGE_ACCOUNT already exists"
    else
        az storage account create \
            --name $STORAGE_ACCOUNT \
            --resource-group $RESOURCE_GROUP \
            --location $LOCATION \
            --sku Standard_LRS \
            --encryption-services blob \
            --https-only true \
            --min-tls-version TLS1_2
        print_status "Storage account created successfully"
    fi
    
    # Get storage account key
    STORAGE_KEY=$(az storage account keys list \
        --resource-group $RESOURCE_GROUP \
        --account-name $STORAGE_ACCOUNT \
        --query '[0].value' -o tsv)
    
    # Create connection string
    export AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=$STORAGE_ACCOUNT;AccountKey=$STORAGE_KEY;EndpointSuffix=core.windows.net"
    
    print_status "Storage connection string configured"
}

# Function to create storage containers
create_containers() {
    print_status "Creating storage containers..."
    
    containers=($CONTAINER_RAW $CONTAINER_PROCESSED $CONTAINER_MODELS)
    
    for container in "${containers[@]}"; do
        if az storage container show --name $container --account-name $STORAGE_ACCOUNT &> /dev/null; then
            print_warning "Container $container already exists"
        else
            az storage container create \
                --name $container \
                --account-name $STORAGE_ACCOUNT \
                --auth-mode key
            print_status "Container $container created"
        fi
    done
}

# Function to create a service principal for the application
create_service_principal() {
    print_status "Creating service principal for authentication..."
    
    APP_NAME="xray-triage-app"
    
    # Check if app registration already exists
    if az ad app list --display-name $APP_NAME --query "[].appId" -o tsv | grep -q .; then
        print_warning "App registration $APP_NAME already exists"
        APP_ID=$(az ad app list --display-name $APP_NAME --query "[0].appId" -o tsv)
    else
        # Create app registration
        APP_ID=$(az ad app create --display-name $APP_NAME --query appId -o tsv)
        print_status "App registration created: $APP_ID"
    fi
    
    # Create service principal
    if az ad sp show --id $APP_ID &> /dev/null; then
        print_warning "Service principal already exists"
    else
        az ad sp create --id $APP_ID
        print_status "Service principal created"
    fi
    
    # Create client secret
    CLIENT_SECRET=$(az ad app credential reset --id $APP_ID --query password -o tsv)
    
    # Get tenant ID
    TENANT_ID=$(az account show --query tenantId -o tsv)
    
    # Assign Storage Blob Data Contributor role
    SUBSCRIPTION_ID=$(az account show --query id -o tsv)
    SCOPE="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$STORAGE_ACCOUNT"
    
    az role assignment create \
        --assignee $APP_ID \
        --role "Storage Blob Data Contributor" \
        --scope $SCOPE
    
    print_status "Service principal configured with Storage Blob Data Contributor role"
    
    # Save credentials to file
    cat > azure_credentials.env << EOF
# Azure Service Principal Credentials
AZURE_TENANT_ID=$TENANT_ID
AZURE_CLIENT_ID=$APP_ID
AZURE_CLIENT_SECRET=$CLIENT_SECRET
AZURE_SUBSCRIPTION_ID=$SUBSCRIPTION_ID
AZURE_STORAGE_ACCOUNT_NAME=$STORAGE_ACCOUNT
AZURE_STORAGE_CONNECTION_STRING="$AZURE_STORAGE_CONNECTION_STRING"
EOF
    
    print_status "Credentials saved to azure_credentials.env"
    print_warning "Keep azure_credentials.env secure and do not commit to git!"
}

# Function to install Python dependencies
install_dependencies() {
    print_status "Installing Python dependencies..."
    
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 is not installed"
        exit 1
    fi
    
    # Create virtual environment if it doesn't exist
    if [ ! -d "venv" ]; then
        python3 -m venv venv
        print_status "Virtual environment created"
    fi
    
    # Activate virtual environment
    source venv/bin/activate
    
    # Install required packages
    pip install --upgrade pip
    pip install azure-storage-blob azure-identity requests pandas tqdm
    
    print_status "Python dependencies installed"
}

# Function to download NIH dataset to Azure
download_dataset() {
    print_status "Starting NIH dataset download to Azure Storage..."
    
    # Check if user wants sample or full dataset
    echo ""
    echo "Choose dataset download option:"
    echo "1) Sample dataset (2 tar files, ~8GB, ~20K images)"
    echo "2) Full dataset (12 tar files, ~45GB, ~112K images)"
    echo "3) Skip dataset download"
    read -p "Enter choice (1-3): " choice
    
    case $choice in
        1)
            print_status "Downloading sample dataset..."
            source venv/bin/activate
            python3 scripts/azure_nih_downloader.py \
                --storage-account $STORAGE_ACCOUNT \
                --container $CONTAINER_RAW \
                --sample-only
            ;;
        2)
            print_status "Downloading full dataset..."
            print_warning "This will take several hours and use ~45GB of storage"
            read -p "Are you sure you want to continue? (y/N): " confirm
            if [[ $confirm == [yY] || $confirm == [yY][eE][sS] ]]; then
                source venv/bin/activate
                python3 scripts/azure_nih_downloader.py \
                    --storage-account $STORAGE_ACCOUNT \
                    --container $CONTAINER_RAW
            else
                print_status "Dataset download cancelled"
            fi
            ;;
        3)
            print_status "Skipping dataset download"
            ;;
        *)
            print_warning "Invalid choice, skipping dataset download"
            ;;
    esac
}

# Function to verify the setup
verify_setup() {
    print_status "Verifying Azure setup..."
    
    # Check resource group
    if az group show --name $RESOURCE_GROUP &> /dev/null; then
        print_status "✓ Resource group exists"
    else
        print_error "✗ Resource group not found"
    fi
    
    # Check storage account
    if az storage account show --name $STORAGE_ACCOUNT --resource-group $RESOURCE_GROUP &> /dev/null; then
        print_status "✓ Storage account exists"
    else
        print_error "✗ Storage account not found"
    fi
    
    # Check containers
    containers=($CONTAINER_RAW $CONTAINER_PROCESSED $CONTAINER_MODELS)
    for container in "${containers[@]}"; do
        if az storage container show --name $container --account-name $STORAGE_ACCOUNT &> /dev/null; then
            print_status "✓ Container $container exists"
        else
            print_error "✗ Container $container not found"
        fi
    done
    
    # Check if credentials file exists
    if [ -f "azure_credentials.env" ]; then
        print_status "✓ Credentials file exists"
    else
        print_error "✗ Credentials file not found"
    fi
}

# Function to display next steps
show_next_steps() {
    print_status "Setup complete! Next steps:"
    echo ""
    echo "1. Load your credentials:"
    echo "   source azure_credentials.env"
    echo ""
    echo "2. Verify your dataset in Azure Portal:"
    echo "   https://portal.azure.com/"
    echo "   Navigate to Storage Account: $STORAGE_ACCOUNT"
    echo "   Check container: $CONTAINER_RAW"
    echo ""
    echo "3. Start developing your model:"
    echo "   python3 scripts/azure_nih_downloader.py --help"
    echo ""
    echo "4. Your Azure resources:"
    echo "   - Resource Group: $RESOURCE_GROUP"
    echo "   - Storage Account: $STORAGE_ACCOUNT"
    echo "   - Containers: $CONTAINER_RAW, $CONTAINER_PROCESSED, $CONTAINER_MODELS"
    echo ""
    print_warning "Remember to keep azure_credentials.env secure!"
}

# Main execution
main() {
    echo "=============================================="
    echo "Azure X-ray Triage System Setup"
    echo "=============================================="
    echo ""
    
    check_azure_cli
    azure_login
    create_resource_group
    create_storage_account
    create_containers
    create_service_principal
    install_dependencies
    download_dataset
    verify_setup
    show_next_steps
}

# Handle script arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --resource-group)
            RESOURCE_GROUP="$2"
            shift 2
            ;;
        --storage-account)
            STORAGE_ACCOUNT="$2"
            shift 2
            ;;
        --location)
            LOCATION="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --resource-group     Azure resource group name (default: xray-triage-rg)"
            echo "  --storage-account    Azure storage account name (default: xraytriagestorage)"
            echo "  --location          Azure region (default: eastus)"
            echo "  --help              Show this help message"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Run main function
main