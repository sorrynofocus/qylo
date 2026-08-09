using 'main.bicep'

param location = 'westus'
// Azure resource group name
param resourceGroupName = 'rg-foundry-ai'
// Azure OpenAI account name
param accountName = 'ai-res-platform-default'

param modelVersion = '2025-08-07'

// accountName, deploymentName, modelName, skuCapacity already default to the existing resource's values in main.bicep
