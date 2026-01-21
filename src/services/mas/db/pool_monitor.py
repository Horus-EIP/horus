from prometheus_client import Gauge
from sqlalchemy import event

DB_POOL_SIZE = Gauge("db_pool_size", "Taille totale du pool de connexions")
DB_POOL_CHECKEDIN = Gauge(
    "db_pool_checkedin", "Nombre de connexions disponibles (au repos)"
)
DB_POOL_CHECKEDOUT = Gauge(
    "db_pool_checkedout", "Nombre de connexions actives (utilisées)"
)
DB_POOL_OVERFLOW = Gauge(
    "db_pool_overflow", "Nombre de connexions supplémentaires (overflow)"
)


def attach_pool_monitor(engine):
    @event.listens_for(engine, "connect")
    def receive_connect(dbapi_connection, connection_record):
        update_metrics(engine)

    @event.listens_for(engine, "checkout")
    def receive_checkout(dbapi_connection, connection_record, connection_proxy):
        update_metrics(engine)

    @event.listens_for(engine, "checkin")
    def receive_checkin(dbapi_connection, connection_record):
        update_metrics(engine)


def update_metrics(engine):
    pool = engine.pool

    DB_POOL_SIZE.set(pool.size())
    DB_POOL_CHECKEDIN.set(pool.checkedin())
    DB_POOL_CHECKEDOUT.set(pool.checkedout())
    DB_POOL_OVERFLOW.set(pool.overflow())
