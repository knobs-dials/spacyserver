# spacyserver

A small HTTP-served app that serves spacy's parsing from a persistent process,
to do continuing work without incurring a whole bunch of startup time.

When run, starts a little HTTP-served web-app (WSGI internally) that
- loads configured models (currently hardcoded to `en_core_web_lg`,`nl_core_news_lg`),
- takes form-style data with text in `q`
- determines language of that text, selects model based on that detection
- runs model on that text
- picks out some things to send in JSON response and returns that

Upsides:
- You can quickly add text parsing to a notebook, webapp, or CLI tool,
  without adding much code or dependencies to that.

- decently fast - the startup time was incurred a long time ago,
  and for small pices of text, even CPU models seem to take on the rough order of 20ms per 100 words.

- including SVG dependency tree if you want it

- ...and anything you bolt on


Arguables / downsides:
- this is not necessary in most batch use, or in most notebooks, 
  because you're loading the model to use it persistently, you also incur that startup cost just once,
  and you are not limited to just the parts we serialized:

- It returns our own flattened-data version of the spacy objects (cherry-picking some attributes to put in JSON)
  - (yes, in theory spacy allows you to serialize the objects, but in practice this is messy and very inefficient)
  - so we added yet another variant, 'yay'.
  - and there are plenty of things you couldn't really implement client-side without more work

- not concurrent (yet?)
  If indeed you put this up for shared/public consumption,
  it will slow down with amount of users even if you had computing power to spare


## spacy_server.py

The server part of the server:
- load models you need
- wraps the it in a WSGI app
- where for each request, decides which model you need for a piece of text

## api_spacyserver.py

The functional part of using one model on one piece of text, and deciding what to return:
- `http_api()` is used by the client, which feeds the given text to a running spacy_server
- `parse()` is used by the server hander (that runs as a result of calling http_api on the client side)
  - feeds text to an instantiated model.
  - decides what to take from the resulting parse
  - includes a hacky transform of the SVG dependency image, if you want it


## spacyserver-cli

A script that you give some text, and prints out with some pretty colors. 

It is meant as a visual example - you probably want to copy it and do something more useful with the dict it spits out.

![CLI example](screenshots/cli_cheese.png?raw=true)


## web-served example

![Webpage example](screenshots/web_cheese.png?raw=true)

TODO: put the JS for that here too


