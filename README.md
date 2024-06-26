# wetsuite-spacyserver

A small HTTP-served app that serves spacy's parsing from a persistent process,
to do continuing work without incurring a whole bunch of startup time.

There is a function in the wetsuite library that lets you consume this from code.
TODO: separate from those origins so this stands alone.

Upsides:
- You can have a webapp, or CLI tool, give you parses of small text quickly
  (CPU models seem to take on the rough order of 20ms per 100 words)

- including SVG dependency tree

- ...and anything you bolt on


Arguables / downsides:
- Depends on functions in the wetsuite core - could be moved

- It returns our own flattened-data version of the spacy objects (cherry-picking things to put in JSON)
  - so it's yet another variant, and for anything nontrivial you may want to impement on the spacy side, not this receiving side
  - (yes, in theory spacy allows you to serialize the objects, but in practice this is messy and very inefficient)

- not necessary in most batch use or in most notebooks, 
  because you're loading the model to use it persistently and you're fine to incur that startup cost just once

- not concurrent (yet?)
  If indeed you put this up for public consumption, it will slow down with amount of users
  even if you had computing power to spare


