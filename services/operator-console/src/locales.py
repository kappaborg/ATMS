"""Operator console localization — minimal per-locale string tables.

Reads `region.operator_locale` from the site YAML the chamber was
booted with (forwarded via the state JSON's `decision.locale` field).
Falls back to English when an entry is missing or locale isn't set.

Supported locales (Phase 5 pilot scope):
  en — English (default)
  bs — Bosnian (Latin script)
  tr — Turkish

Extending: add a new dict + register in LOCALES below. Strings are
keyed by short, stable identifiers so we don't have to track every
literal in the codebase.
"""

from __future__ import annotations

EN = {
    "console_title": "ATMS Operator Console",
    "console_subtitle": (
        "Live state from the SUMO demo orchestrator. "
        "Start a demo with `python -m simulation.demo` in another terminal."
    ),
    "operator_controls": "Operator controls",
    "ped_request_label": "Pedestrian request",
    "ped_direction_label": "Direction needing crossing",
    "ped_request_button": "Request pedestrian phase",
    "ped_request_success": "Ped request submitted for {direction} (valid 60s)",
    "emg_preempt_label": "Emergency preempt",
    "emg_direction_label": "Direction needing preempt",
    "emg_preempt_button": "Force emergency preempt",
    "emg_preempt_warning": "Emergency preempt for {direction} (valid 45s)",
    "clear_overrides_label": "Clear overrides",
    "clear_overrides_caption": "Removes any active ped / emergency request files",
    "clear_overrides_button": "Clear all signals",
    "clear_overrides_info": "All overrides cleared",
    "chamber_panel_header": "AI Decision Chamber",
    "closed_loop_header": "Closed-loop NTCIP",
    "closed_loop_in_sync": "in sync ✓",
    "closed_loop_no_readback": "no read-back",
    "closed_loop_diverge": "DIVERGE ({n} ticks)",
    "tsp_header": "Transit Signal Priority — active",
    "tsp_none": "TSP: no late buses active",
    "detector_health_header": "Detector + protocol coverage",
    "priority_scores": "Priority scores",
    "reasoning_trace": "Reasoning trace",
    "rule_winner_badge": "winner",
}

BS = {
    "console_title": "ATMS Operatorska Konzola",
    "console_subtitle": (
        "Stanje uživo iz SUMO demo orkestratora. "
        "Pokrenite demo sa `python -m simulation.demo` u drugom terminalu."
    ),
    "operator_controls": "Operatorske kontrole",
    "ped_request_label": "Zahtjev za pješake",
    "ped_direction_label": "Smjer koji traži prijelaz",
    "ped_request_button": "Zatraži pješačku fazu",
    "ped_request_success": "Pješački zahtjev poslan za {direction} (važi 60s)",
    "emg_preempt_label": "Hitno preuzimanje",
    "emg_direction_label": "Smjer koji traži preuzimanje",
    "emg_preempt_button": "Pokreni hitno preuzimanje",
    "emg_preempt_warning": "Hitno preuzimanje za {direction} (važi 45s)",
    "clear_overrides_label": "Obriši preuzimanja",
    "clear_overrides_caption": "Briše sve aktivne pješačke / hitne zahtjeve",
    "clear_overrides_button": "Obriši sve signale",
    "clear_overrides_info": "Sva preuzimanja obrisana",
    "chamber_panel_header": "AI Komora Odluka",
    "closed_loop_header": "Zatvorena petlja NTCIP",
    "closed_loop_in_sync": "sinhronizovano ✓",
    "closed_loop_no_readback": "nema očitavanja",
    "closed_loop_diverge": "RASKORAK ({n} otkucaja)",
    "tsp_header": "Prioritet javnog prijevoza — aktivan",
    "tsp_none": "TSP: nema autobusa u kašnjenju",
    "detector_health_header": "Pokrivenost detektora + protokola",
    "priority_scores": "Bodovi prioriteta",
    "reasoning_trace": "Trag obrazloženja",
    "rule_winner_badge": "pobjednik",
}

TR = {
    "console_title": "ATMS Operatör Konsolu",
    "console_subtitle": (
        "SUMO demo orkestratöründen canlı durum. "
        "Başka bir terminalde `python -m simulation.demo` ile demo başlatın."
    ),
    "operator_controls": "Operatör kontrolleri",
    "ped_request_label": "Yaya talebi",
    "ped_direction_label": "Geçişe ihtiyaç duyan yön",
    "ped_request_button": "Yaya fazı talep et",
    "ped_request_success": "{direction} için yaya talebi gönderildi (60s geçerli)",
    "emg_preempt_label": "Acil durum geçer akçe",
    "emg_direction_label": "Geçer akçe gereken yön",
    "emg_preempt_button": "Acil durumu zorla",
    "emg_preempt_warning": "{direction} için acil geçer akçe (45s geçerli)",
    "clear_overrides_label": "Geçer akçeleri temizle",
    "clear_overrides_caption": "Aktif yaya / acil durum talep dosyalarını kaldırır",
    "clear_overrides_button": "Tüm sinyalleri temizle",
    "clear_overrides_info": "Tüm geçer akçeler temizlendi",
    "chamber_panel_header": "AI Karar Odası",
    "closed_loop_header": "Kapalı döngü NTCIP",
    "closed_loop_in_sync": "senkron ✓",
    "closed_loop_no_readback": "geri okuma yok",
    "closed_loop_diverge": "RASKORAK ({n} tick)",
    "tsp_header": "Toplu taşıma sinyal önceliği — aktif",
    "tsp_none": "TSP: gecikmiş otobüs yok",
    "detector_health_header": "Dedektör + protokol kapsamı",
    "priority_scores": "Öncelik skorları",
    "reasoning_trace": "Mantık izi",
    "rule_winner_badge": "kazanan",
}


LOCALES = {
    "en": EN,
    "bs": BS,
    "tr": TR,
}


def t(locale: str, key: str, **kwargs) -> str:
    """Translate `key` for `locale`. Falls back to English then to the
    key itself. Supports `{name}` keyword interpolation.
    """
    table = LOCALES.get(locale) or EN
    value = table.get(key) or EN.get(key) or key
    if kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, IndexError):
            return value
    return value
