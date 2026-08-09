# Infra: Azure OpenAI deployment for QnA-Chatbot

This is a declarative Bicep template and Python wrapper to provision the Azure OpenAI `gpt-5-nano` model deployment that this app uses. This is a modern way to deploy Azure resources, instead of manually clicking through the Azure Portal or Foundry UI.


## Prerequisites

- Python 3 (stdlib only no packages to install for `deploy.py`).
- Azure CLI (`az`) installed and on `PATH`. Bicep support is built into `az`;  no separate Bicep install needed. The install is really easy and can be found here: https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows?view=azure-cli-latest&pivots=msi
- Logged into Azure via `az cli`, or ready to log in interactively (`deploy.py` will call `az login` for you if needed).
- An Azure resource group, Foundry account, Foundry project, in Azure.

> Tip: if you only have one Azure subscription, `az config set core.login_experience_v2=off` (once, machine-wide - not project-specific) skips the interactive subscription picker on every future `az login`.


In order to get things setup, there are things you need in Azure first (resource group, Foundry account, Foundry project). In your Azure subscription, create a resource group, 
then create a Foundry account in that resource group, and then create a Foundry project in that account. In this document, there are provided names for the resource group, 
Foundry account, and Foundry project that you can use, or you can choose your own names (just modify the files needed).

| Resource | Value |
| --- | --- |
| Resource group | `rg-foundry-ai` |
| Foundry account | `ai-res-platform-default` (API Kind: `AIServices`) |
| Foundry project | `ws-foundry-default` (Parent resource: `ai-res-platform-default`) |
| AI model deployment | `gpt-5-nano-deploy` |

> Tip: Once you get the resource group, foundry account and project setup, the only thing that needs to be changed in the `main.bicepparam` file is the `subscriptionId` and `tenantId` values. 
> The rest of the values can remain as-is, unless you want to change the names of the resources.

## Create a resource group:

```sh
az group create --name rg-foundry-ai --location westus 
```

## Create a Foundry account in that resource group:

```sh
az cognitiveservices account create \
  --name ai-res-platform-default \
  --resource-group rg-foundry-ai \
  --kind AIServices \
  --sku GlobalStandard \
  --location westus \
  --yes
``` 

## Create Foundry Project in that account:

```sh
az cognitiveservices account project create \
  --name ai-res-platform-default \
  --resource-group rg-foundry-ai \
  --project-name ai-res-platform-default \
  --description "Default project for Foundry AI resources"
```


## `main.bicepparam` 

Fill in your subscription-specific values. `main.bicepparam` already has this repo's actual values filled in (values from above), so re-run these only if you're pointing at a different subscription/account, or the model version changes):


### Check the existing account and model version

```sh
# Resource group and region of the existing account
az cognitiveservices account show --name ai-res-platform-default --resource-group rg-foundry-ai --query "{resourceGroup:resourceGroup, location:location}" -o table

# Model version currently deployed
az cognitiveservices account list-models --name ai-res-platform-default --resource-group rg-foundry-ai --query "[?name=='gpt-5-nano']" -o table
```

(`account show` needs `-g`/`--resource-group` — it looks *up* an account you already know the group for, it doesn't discover the group for you.)

Expected output:

| ResourceGroup | Location |
| --- | --- |
| rg-foundry-ai | westus |

| Format | Name | Version | IsDefaultVersion | MaxCapacity | ModelCatalogAssetId | LifecycleStatus |
| --- | --- | --- | --- | --- | --- | --- |
| OpenAI | gpt-5-nano | 2025-08-07 | True | 3 | azureml://registries/azure-openai/models/gpt-5-nano/versions/2025-08-07 | GenerallyAvailable |




## Usage

`--validate` and `--dry-run` are __different__ checks, not two names for the same thing. Both are safe (no changes), but they answer different questions:

- **`--validate`** - is this template/parameter combination well-formed and would Azure *accept* it? (Schema/preflight checks: this is what caught the `kind` and SKU mismatches during this template's own first development run.) Does **not** show what would actually change.
- **`--dry-run`** - exactly what *would* change if you ran this for real (added/modified/deleted, property-by-property). Runs `az deployment sub what-if` under the hood. This is the one to reach for before every real apply.

Check the template is well-formed first:

```sh
python deploy.py --location westus --validate
```

Then preview the exact diff before applying:

```sh
python deploy.py --location westus --dry-run
```

Apply for real:

```sh
python deploy.py --location westus
```

Add `--tenant <tenant-id>` to any of the above if you need to sign into a non-default Azure AD tenant.

## After deploying

This only provisions the resource. It does not output the key, endpoint, or model deploy name. You need to fetch those values yourself and put them in `.env` for the app to use. See `env.example` for the variable names.

- Get the endpoint for the Foundry account:
```sh
az cognitiveservices account show --name ai-res-platform-default --resource-group rg-foundry-ai --query "properties.endpoint" -o tsv
``` 
 
- Get the API key for the Foundry account:
```sh
az cognitiveservices account keys list --name ai-res-platform-default --resource-group rg-foundry-ai --query "key1" -o tsv
```

- Get the model deployment name (should be `gpt-5-nano-deploy`):
```sh
az cognitiveservices account deployment list --resource-group  rg-foundry-ai --name ai-res-platform-default --output table
```

- Get the API version for the model (should be `2024-12-01-preview`):
```sh
az cognitiveservices account list-models --name ai-res-platform-default --resource-group rg-foundry-ai --query "[?name=='gpt-5-nano'].apiVersion" -o tsv
```

Then add these values to your `.env` file:




### Gotchas!

Just a few things that tripped up the initial development of this template, and that you might run into if you try to apply it to a different subscription/account. These are simple mistakes anyone can make --and I made them pointing out the failures here. 

- **Account `kind` must match the existing resource's kind, not the narrower `OpenAI` kind.** Azure Foundry-created accounts are typically `kind: 'AIServices'` (this repo's own account is), and Azure rejects `az deployment ... validate`/`create` with `RollbackToOpenAIKindNotAllowed` if the template's `kind` doesn't match what's already there. Check yours with:
  ```sh
  az cognitiveservices account show --name ai-res-platform-default --resource-group rg-foundry-ai --query kind -o tsv
  ```
  
Expected output:

```AIServices```


- **SKU name and capacity __must__ match what the model version actually supports and what's already deployed.** Models (like `gpt-5-nano`) are often only available under `GlobalStandard`, not the older `Standard` SKU. Using the wrong one fails validation with `InvalidResourceProperties`. Separately, `skuCapacity` isn't just a placeholder default. If it doesn't match the live deployment's actual capacity, a real `create` would *change* (downgrade) that deployment's throughput. Check the live deployment's SKU before assuming any default is safe:
  ```sh
  az cognitiveservices account deployment show --name ai-res-platform-default --resource-group rg-foundry-ai --deployment-name gpt-5-nano-deploy --query "sku"
  ```
Expected output:

```json
{
  "capacity": 250,
  "family": null,
  "name": "GlobalStandard",
  "size": null,
  "tier": null
}
```


- **`--dry-run` (`what-if`) can reveal that "targeting the right resource" isn't the same as "safe to apply."** Even if the template is well-formed and points at the right resource, if the SKU/capacity doesn't match the live deployment (for example), `--dry-run` will show that it would *change* that deployment's throughput. If you see that, fix the `main.bicepparam` values to match the live deployment before applying.
