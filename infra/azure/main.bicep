targetScope = 'subscription'

@description('Azure region for the resource group and OpenAI account.')
param location string

@description('Resource group to create (if missing) and deploy into.')
param resourceGroupName string

@description('Cognitive Services / Azure OpenAI account name.')
param accountName string

@description('Model deployment name.')
param deploymentName string = 'gpt-5-nano-deploy'

@description('Model name to deploy.')
param modelName string = 'gpt-5-nano'

@description('Model version - look up with az cognitiveservices account list-models.')
param modelVersion string

@description('Deployment SKU capacity (throughput units).')
param skuCapacity int = 250

resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: resourceGroupName
  location: location
}

module openai 'modules/openai-deployment.bicep' = {
  name: 'openaiDeployment'
  scope: rg
  params: {
    location: location
    accountName: accountName
    deploymentName: deploymentName
    modelName: modelName
    modelVersion: modelVersion
    skuCapacity: skuCapacity
  }
}

output endpoint string = openai.outputs.endpoint
output deploymentName string = deploymentName
