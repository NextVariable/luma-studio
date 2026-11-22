"""Published list-price estimates. A quote is not a provider spending cap."""
from decimal import Decimal

from . import domestic_media, fal_media
from . import openai_direct


def estimate(kind, provider, model=None, duration=None, instruction='', resolution=None):
    dollars = None
    calls = 1
    if model in domestic_media.PROVIDER and domestic_media.PROVIDER[model] == provider:
        if model == domestic_media.HAILUO:
            price = domestic_media.HAILUO_PRICES.get((duration, resolution))
            return dict(provider=provider, model=model, duration=duration, resolution=resolution,
                        estimated_cny=price, estimated_usd=None, authorization_calls=1,
                        billing=f'预计 ¥{price}（人民币）' if price else '待确定时长和分辨率')
        yuan = Decimal(domestic_media.STILL_MODELS[model][1]) if model in domestic_media.STILL_MODELS else Decimal('0.15') * int(duration)
        return dict(provider=provider, model=model, duration=duration, estimated_cny=format(yuan,'.2f'),
                    estimated_usd=None, authorization_calls=1, billing=f'预计 ¥{yuan:.2f}（人民币）')
    if provider == 'fal':
        if model in (fal_media.IMAGE, fal_media.TEXT_IMAGE):
            dollars = Decimal('0.04')
        elif model == fal_media.STORYBOARD:
            dollars = Decimal('0.0398')
        elif model == fal_media.VIDEO and duration in (5, 10):
            dollars = Decimal('0.07') * int(duration)
        billing = '按实际生成计费' if dollars is not None else '由服务商结算，暂无单价'
    elif provider == 'openai':
        if kind == 'audio':
            billing = '按实际文字和语音用量计费。仅音频输出约 $0.024/分钟'
        else:
            calls = 1 if openai_direct.CAMERA_ONLY.fullmatch(instruction.strip()) else 2
            billing = '按实际文字用量计费'
    else:
        billing = '按 Dify 积分或所用模型账户结算，金额取决于工作流实际调用'
    return {'provider': provider, 'model': model, 'duration': duration,
            'estimated_usd': str(dollars) if dollars is not None else None,
            'authorization_calls': calls, 'billing': billing}
