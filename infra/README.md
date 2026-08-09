# Infra

Two independent pieces of infrastructure live here. They solve different problems and are
frequently used **together**, so read this page before assuming you need to pick one.

| Directory | Provisions | Prerequisite |
| --- | --- | --- |
| [`azure/`](azure/README.md) | The **cloud resource** — an Azure OpenAI `gpt-5-nano` model deployment, via Bicep | Azure CLI (`az`) on `PATH` |
| [`docker/`](docker/README.md) | The **application** — a container image with every dependency baked in | Docker |

## They are complementary, not alternatives

This is the part that trips people up. `azure/` creates *the model you talk to*. `docker/`
packages *the thing that talks to it*. Neither replaces the other:

- Running the Docker image with `CHATBOT_MODEL_PROVIDER=azure` still needs an endpoint and
  API key in `.env` — and that endpoint is what `azure/` provisions.
- Running the Docker image with `CHATBOT_MODEL_PROVIDER=local` needs no Azure at all. The
  image ships llama.cpp and the Qwen weights, so it is fully self-contained.

## Which do I want?

| Goal | Path |
| --- | --- |
| Provision or re-provision the Azure model deployment | `azure/` — see [azure/README.md](azure/README.md) |
| Run the app without installing Python, `uv`, or llama.cpp on the host | `docker/` — see [docker/README.md](docker/README.md) |
| Fully self-contained / air-gapped install (no network at run time) | `docker/`, default build (weights baked in) |
| Build in CI/CD | `docker/` — see the workflow notes in [docker/README.md](docker/README.md) |
| Develop locally against the source tree | Neither. Follow `## Setup` in the [root README](../README.md) |

## Layout

```text
infra/
├── README.md                          # this file
├── azure/                             # Azure OpenAI resource provisioning (Bicep + az wrapper)
│   ├── README.md
│   ├── deploy.py                      # thin az CLI wrapper: validate / what-if / create
│   ├── main.bicep                     # subscription-scoped: resource group + module
│   ├── main.bicepparam                # checked-in parameter values
│   └── modules/
│       └── openai-deployment.bicep    # the AIServices account + model deployment
└── docker/                            # container packaging for the app itself
    ├── README.md
    ├── Dockerfile                     # six-stage build
    ├── docker-compose.yml             # chatbot + optional llama-server sibling
    └── entrypoint.sh                  # dispatch: default / serve / batch
```

> The Docker build context is the **repository root**, not `infra/docker/`. Build with
> `docker build -f infra/docker/Dockerfile .` from the root — see
> [docker/README.md](docker/README.md) for why.
