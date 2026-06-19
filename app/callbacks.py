from aiogram.filters.callback_data import CallbackData


class UserID(CallbackData, prefix='user'):
    user_id: int


class PlanCallback(CallbackData, prefix='plan'):
    period: str  # "month" | "year"


class DeleteMsg(CallbackData, prefix='del'):
    db_id: int  # messages.id of the stored record to delete
