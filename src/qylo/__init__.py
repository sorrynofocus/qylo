"""
Qylo package - a grounded question-answering and CLI-command assistant.

The module layout IS the request flow. Read them in this order and you have
walked one question end to end:

    cli.py                1.  entry: parse args, wire things up, run
    settings.py           1a. defaults and .env resolution
    documents.py          2.  scan, load, split source documents
    retrieval.py          3.  embed, index, search them
    model_provider.py     4.  build the chat backend (Azure or local)
    assistant.py          5.  agent loop: retrieve -> decide -> answer
    response_contract.py  6.  turn the reply into a ModelResponse
    console.py            7.  print it
    execution.py          8.  gate it, then run it

    string_table.py       cross-cutting: every user-facing and error string
    system_prompt.txt     the bundled instruction prompt (model-facing text)

Nothing is imported here on purpose. cli.py defers the heavy stages (2, 3, 5)
until after argument parsing so --help stays fast; an eager import in this file
would silently undo that.
"""
