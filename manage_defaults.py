"""Default, non-secret management data for the local operations center."""

from __future__ import annotations


DEFAULT_ASN_RECOMMENDATIONS = {
    "GB": {
        "label": "英国",
        "region": "",
        "items": [
            {"asn": "AS2856", "provider": "BT", "tier": "A", "note": "综合首选 · 大型家庭宽带"},
            {"asn": "AS5607", "provider": "Sky UK", "tier": "A", "note": "家庭宽带 · 覆盖较广"},
            {"asn": "AS5089", "provider": "Virgin Media", "tier": "A", "note": "家庭宽带 · 固定线路"},
            {"asn": "AS13285", "provider": "TalkTalk", "tier": "A", "note": "家庭 ISP · 覆盖较广"},
            {"asn": "AS13037", "provider": "Zen", "tier": "A", "note": "家庭 ISP · 网络质量稳定"},
            {"asn": "AS6871", "provider": "Plusnet", "tier": "A", "note": "家庭 ISP · BT 体系"},
            {"asn": "AS9105", "provider": "TalkTalk", "tier": "B", "note": "TalkTalk 相关家庭网络"},
            {"asn": "AS12390", "provider": "KCOM", "tier": "B", "note": "区域 ISP · 主要覆盖 Hull 一带"},
            {"asn": "AS43915", "provider": "TrueSpeed", "tier": "B", "note": "区域 FTTP · 西南英格兰"},
            {"asn": "AS201838", "provider": "Community Fibre", "tier": "B", "note": "伦敦本地光纤"},
            {"asn": "AS56478", "provider": "Hyperoptic", "tier": "B", "note": "城市光纤 · 覆盖受限"},
            {"asn": "AS48101", "provider": "Trooli", "tier": "B", "note": "区域光纤"},
            {"asn": "AS56329", "provider": "Gigaclear", "tier": "B", "note": "乡村光纤 · 覆盖受限"},
            {"asn": "AS5482", "provider": "AllPoints Fibre", "tier": "B", "note": "区域光纤"},
            {"asn": "AS212655", "provider": "YouFibre", "tier": "B", "note": "区域光纤"},
            {"asn": "AS207995", "provider": "Lightning Fibre", "tier": "B", "note": "区域光纤"},
            {"asn": "AS60377", "provider": "toob", "tier": "B", "note": "区域 FTTH"},
            {"asn": "AS48294", "provider": "Ogi Networks", "tier": "B", "note": "威尔士本地光纤"},
            {"asn": "AS42611", "provider": "Full Fibre", "tier": "B", "note": "区域光纤"},
            {"asn": "AS205847", "provider": "GoFibre", "tier": "B", "note": "苏格兰区域光纤"},
            {"asn": "AS199775", "provider": "Connexin", "tier": "B", "note": "区域宽带/光纤"},
            {"asn": "AS199468", "provider": "Grain", "tier": "B", "note": "区域光纤"},
            {"asn": "AS213671", "provider": "Vision Fibre", "tier": "B", "note": "区域光纤"},
            {"asn": "AS60426", "provider": "WightFibre", "tier": "B", "note": "区域光纤 · 覆盖受限"},
            {"asn": "AS57099", "provider": "Quickline", "tier": "B", "note": "乡村宽带 · 覆盖受限"},
            {"asn": "AS207645", "provider": "F&W Networks", "tier": "B", "note": "小型区域 ISP · 需核验城市"},
            {"asn": "AS35437", "provider": "Zone Telecom", "tier": "B", "note": "小型 ISP · 需核验具体 IP"},
            {"asn": "AS206067", "provider": "Three UK", "tier": "C", "note": "移动网络 · 可能 CGNAT"},
            {"asn": "AS35228", "provider": "O2 UK", "tier": "C", "note": "移动网络 · 可能 CGNAT"},
            {"asn": "AS14593", "provider": "Starlink", "tier": "C", "note": "卫星网络 · 不作为固定宽带首选"},
            {"asn": "AS25135", "provider": "Vodafone", "tier": "C", "note": "Vodafone 相关 · 需核验 IP 类型"},
            {"asn": "AS25310", "provider": "Vodafone", "tier": "C", "note": "Vodafone 相关 · 需核验 IP 类型"},
            {"asn": "AS5378", "provider": "Vodafone", "tier": "C", "note": "Vodafone 相关 · 需核验 IP 类型"},
            {"asn": "AS31655", "provider": "Gamma Telecom", "tier": "C", "note": "企业/电信网络 · 需核验"},
            {"asn": "AS25369", "provider": "Hydra", "tier": "C", "note": "企业/托管混合网络 · 需核验"},
        ],
    }
}
