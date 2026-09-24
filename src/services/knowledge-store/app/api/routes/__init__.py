from app.api.routes import corpus, file, store

# Mount order matters. The store router carries the bare "" prefix and owns
# paths like "/{...}", so anything registered after it can be shadowed. Corpus
# also stays OFF the /file router on purpose: file.py declares
# POST /file/{type}, which would swallow POST /file/corpus/scan and answer 422.
ROUTERS: dict = {
    "/file": file.router,
    "/corpus": corpus.router,
    "": store.router,
}
