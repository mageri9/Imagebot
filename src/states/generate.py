from aiogram.fsm.state import State, StatesGroup


class GenerateForm(StatesGroup):
    choosing_mode = State()       # выбор режима: текст / фото / несколько фото
    waiting_prompt = State()      # ждём текстовый промпт (режим text)
    waiting_image = State()       # ждём первое фото
    waiting_more_images = State() # ждём ещё фото или команду генерить
    waiting_image_prompt = State()# ждём промпт после загрузки фото(й)
