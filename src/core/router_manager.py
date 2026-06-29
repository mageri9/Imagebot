from aiogram import Router
import src.handlers.start as start
import src.handlers.generate as generate
import src.handlers.admin as admin


def setup_routers() -> Router:
    root = Router()

    modules = [start, generate, admin]
    for m in modules:
        m.register_handlers()
        root.include_router(m.router)

    return root
