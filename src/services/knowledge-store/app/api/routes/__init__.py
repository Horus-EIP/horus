from app.api.routes import file, store

ROUTERS: dict = {
    "/file": file.router,
    "": store.router
}
