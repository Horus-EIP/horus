from app.api.routes import store
from app.api.routes import file

ROUTERS: dict = {
    "/file": file.router,
    "": store.router
}