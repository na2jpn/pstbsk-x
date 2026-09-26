"""Factory preserving ICOM CI-V and isolating experimental CAT support."""
from .civ import CIVController, radio_address, connect_configured
RIG_MODELS = {
    "IC-705": 0xA4, "IC-7300": 0x94, "IC-7300MK2": 0xB6,
    "IC-7100": 0x88, "IC-9700": 0xA2, "IC-7610": 0x98,
    "IC-905": 0xAC,
}
from .yaesu import YAESU_MODELS, YaesuController


def validate_radio(values):
    model = values.get('model', '')
    if model in YAESU_MODELS:
        if values.get('ptt', 'CAT') != 'CAT':
            raise ValueError('Yaesu試験対応はCATによるPTTを選んでください。')
        if int(values.get('cat_stopbits', 1 if model == 'FTX-1' else 2)) not in (1, 2):
            raise ValueError('ストップビットは1または2です。')
    elif model in RIG_MODELS:
        radio_address(values)
    else:
        raise ValueError('無線機を選択してください。')


def create_controller(values):
    validate_radio(values)
    if values['model'] in YAESU_MODELS:
        return YaesuController(values['model'], values.get('cat_stopbits'))
    return CIVController(radio_address(values), model=values['model'])
