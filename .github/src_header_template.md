# Cwinters / US / Arizona / ThinkPad T15g Gen 1
# 2025.12.15
# RAG CLI assistant to help build command line runs/cli for internal built tools or general query assistant.
#
# Purpose: 
# A utility to help create and  run internal tools cli and typical general queries. 
#
# Usage examples (see README for granular details):
# 
# Ask against all supported files in `data/documents`:
# uv run qylo "What is flogger and what logging features does it support?"
#
# Use a different document folder or file:
# uv run qylo "What does this document say?" --documents path\to\knowledge-base
#
# Ask something the knowledge base doesn't cover
# uv run qylo "Who wrote the novel Moby Dick?"
#