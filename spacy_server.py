#!/usr/bin/python3
''' A small HTTP app that serves spacy's parsing from a persistent process.

    The idea is that clients do intermitted parsing work,
    without incurring a whole bunch of startup time.

    WSGI-style app, served via the basic HTTP server
    TODO: disentangle out app from that

    CONSIDER: 
    - trying to be multicore. That would need
      - letting you specify CPU models multiple times, to load it several times,
        and be able to use the same model on multiple cores?
      - (except we would probably need to engineer around the GIL with multiprocessing?)
      - serving in a way that allows that 
        (e.g. starlette / uvicorn to host most things on a standalone async thing)
      - pick_model to be aware of which ones are currently in use

    - try parsing in smaller chunks, and stream out results    
      - maybe put up a text limit on individual calls?
      - and provide a helper function that makes that easier, even if it's just based on 
        re.split(\n{2,}) and doing multiple calls

    - consider async (except for GPU there is little to no point)
'''

from spacyserver import api_spacyserver
import spacy
import spacy_fastlang    #  pylint: disable=unused-import    it is used, by spacy internally
# note: some imports are done later, mostly to suppress warnings

def load_models( model_list ):
    ''' @param model_list: A list of 3-tuples, each
            - language
            - preference of where to load it - 'cpu' or 'gpu'
            - model name

        @return: a list of 4-tuples:
            - language                                         (as handed in)
            - preference of where to load it - 'cpu' or 'gpu'  (as handed in)
            - model name                                       (as handed in)
            - spacy model object
    '''
    ret = []
    for lang, cpu_or_gpu, model_name in model_list:
        if cpu_or_gpu=='gpu':
            spacy.require_gpu()
        elif cpu_or_gpu=='cpu':
            spacy.require_cpu()
        else:
            raise ValueError( f"Don't understand preference {cpu_or_gpu}" )
        print( f"loading model {model_name}, {cpu_or_gpu}" )
        try:
            ref = spacy.load(model_name)
            # experiments trying to avoid a memory leak
            #for pipename in ('transformer', 'tagger', 'parser', 'ner'):
            #    if ref.has_pipe(pipename):
            #        ref.get_pipe(pipename).model.attrs['flush_cache_chance'] = 1
            ret.append( (lang, cpu_or_gpu, model_name, ref) )
        except OSError:
            print(
                f"ERROR: specified model {repr(model_name)} probably not installed, "+
                f"you may want to do something like:   python -m spacy download {str(model_name)}"
            )
    return ret


def pick_model( loaded_models, lang:str=None, name:str=None, fallback:bool=True):
    ''' Given 
        - what load_models() has done (so its (lang,pref,modelname,modelobject) tuples)
        - your preferences  (probably mainly terms of language, sometimes model name)
        ...returns the model object that is loaded that best fits that.
        
        CONSIDER: implement preference if we have multiple for a language?
    '''
    if name is not None:
        for _,_,model_name, ref in loaded_models:
            if name==model_name:
                return model_name, ref

    if lang is not None:
        for model_lang,_,model_name,ref in loaded_models:
            if model_lang==lang:
                return model_name, ref

    if fallback:
        return loaded_models[0][2], loaded_models[0][3]

    return None,None


_langdet_model = None

def detect_language(text: str):  #  -> tuple(str, float)
    """Note that this depends on spacy, spacy_fastlang, and (because of the last) fasttext.

    Returns (lang, score)
      - lang string as used by spacy          (xx if don't know)
      - score is an approximated certainty

    Depends on spacy_fastlang and loads it on first call of this function.  Which will fail if not installed.

    CONSIDER: truncate the text to something reasonable to not use too much memory.   On parameter?
    """
    # monkey patch done before the import to suppress "`load_model` does not return WordVectorModel or SupervisedModel any more, but a `FastText` object which is very similar."
    try:
        import fasttext  # we depend on spacy_fastlang and fasttext
        fasttext.FastText.eprint = lambda x: None
    except ImportError:
        pass

    global _langdet_model
    if _langdet_model is None:
        # print("first-time load of spacy_fastlang into pipeline")
        _langdet_model = spacy.blank("xx")
        _langdet_model.add_pipe("language_detector")
        # lang_model.max_length = 10000000 # we have a trivial pipeline, though  TODO: still check its memory requirements

    doc = _langdet_model(text)
    return doc._.language, doc._.language_score


if __name__ == '__main__':
    import os
    import sys
    import threading
    import json
    import time
    import argparse

    try: # make it clearer in top and nvidia-smi what this process is
        import setproctitle
        setproctitle.setproctitle( os.path.basename(sys.argv[0]) )
    except ImportError: # ...if you happen to have this package,
        pass            # otherwise just silently ignore it

    from wsgiref.simple_server import make_server
    import paste
    import paste.request
    import torch
    # experiments trying to avoid a library's memory leak  (maybe try-except-pass just in case?)
    torch.set_num_threads(1)
    import spacy

    # NOTE: that detect_language also implies a dependency on spacy_fastlang

    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--model",
                        action="store",
                        dest="model",
                        default="en_core_web_sm",
                        help="Which model to use. "+
                              "Defaults to en_core_web_sm (assumes you have that installed)")
    parser.add_argument("-i", "--bind-ip",
                        action="store",
                        dest="bind_ip",
                        default="0.0.0.0",
                        help="What IP to bind on. "+
                            "Default is all interfaces (0.0.0.0), you might prefer 127.0.0.1")
    parser.add_argument("-p", "--bind-port",
                        action="store",
                        dest='bind_port',
                        default="8282",
                        help="What TCP port to bind on. Default is 8282.")
    # parser.add_argument("-g", "--prefer-gpu",
    #                     action="store_true",
    #                     dest="prefer_gpu",
    #                     default=False,
    #                     help="Whether to try running on GPU (falls back to CPU if it can't).")
    # parser.add_argument("-G", "--require-gpu",
    #                     action="store_true",
    #                     dest="require_gpu",
    #                     default=False,
    #                     help="Whether to run on GPU (fails if it can't).")
    # parser.add_argument('-v', "--verbose",
    #                     action="count",
    #                     default=0,
    #                     help="debug verbosity (repeat for debug)")
    args = parser.parse_args()


    ## prep for serving
    serve_ip = args.bind_ip
    port     = int( args.bind_port )

    ## TODO: separate that out to a "run-with-my-preference" startup script
    models_to_load = [ # try to not occupy the GPU unless you know your're its only user.
        ['en','cpu','en_core_web_lg' ],
        ['nl','cpu','nl_core_news_lg'],
        #['fr','cpu','fr_core_news_md'],
        #['de','cpu','de_core_news_md'],
    ]
    loaded_models = load_models( models_to_load )

    nlp_lock = threading.Lock()  # in case we rewrite for async (CONSIDER: removing until we do)

    ## Serve via HTTP
    def application(environ, start_response):
        ''' Mostly just calls api_spacyserver.parse, 
            which calls nlp() and returns a json-usable dict.   
            Single-purpose, ignores path.
        '''
        output, response_headers = [], []

        reqvars  = paste.request.parse_formvars(environ, include_get_vars=True)
        q        = reqvars.get('q', None)
        want_svg = reqvars.get('want_svg', 'n') == 'y'

        response = {} # collect as dict, will be sent as JSON
        if q in (None,''):
            q = 'You gave us no input.'     # yes, that will get parsed.


        ## Detect the language of input text
        start = time.time()
        lang, _ = detect_language( q )
        response['lang_detect_msec'] = '%d'%(1000*(time.time() - start))
        # CONSIDER: feed language detection only the first so-many words


        ## Choose a fitting model based on detected language
        model_name, nlp = pick_model( loaded_models, lang )
        #print("Using %s: %s for this input"%(lang, model_name))


        ## Do the parse
        #import cupy_backends # purely for underlying exception, see below;
        #  commented to not hardcode a dependency for now
        try:
            # parse() puts the interesting parts of the nlp object in JSON.
            #   this is non-standard and is only understood by some of our own browser code
            #   (also is faster than trying to save/parse as docbin or pickle)
            dic = api_spacyserver.parse( # XXX
                nlp=nlp,
                query_string=q,
                nlp_lock=nlp_lock,
                want_svg=want_svg
            )
            response.update( dic )  # which includes a (server-side) parse time
            response['status'] = 'ok'

        #except cupy_backends.cuda.libs.cublas.CUBLASError as e:
        #    # seems to inherit directly from builtins.RuntimeError,
        #    # so until we specifically need this for "that's probably a memory allocation thing"
        #    # logic, let it pass through to the next case
        #    ret['status'] = 'error'
        #    ret['error']  = str(e)
        except RuntimeError as e:   # Probably "CUDA out of memory" (with details)
            response['status'] = 'error'
            response['error']  = str(e)

        response['model'] = model_name
        response['lang']  = lang

        output = [ json.dumps( response ).encode('utf8') ]

        status='200 OK'
        response_headers.append( ('Content-type',   'application/json') )
        response_headers.append( ('Content-Length', str(sum(len(e) for e in output))) )
        start_response(status, response_headers)
        return output

    server = make_server(serve_ip, port, application)
    print( "  serving" )
    server.serve_forever()
