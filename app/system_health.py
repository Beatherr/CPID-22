def sistem_sagligi_ozetini_olustur(status):
    warnings = []
    recommendations = []
    data_notes = []
    critical = False

    monitored_resources = (
        ("cpu", "İşlemci", "Yoğun işlem yapan uygulamaları kontrol et."),
        ("bellek_yuzde", "Bellek", "Gereksiz uygulamaları kapatmayı düşün."),
        (
            "disk_kullanilan_yuzde",
            "Disk",
            "Diskte yer açmayı veya büyük dosyaları taşımayı düşün.",
        ),
    )
    for key, label, recommendation in monitored_resources:
        value = status.get(key)
        if not isinstance(value, (int, float)):
            continue
        if value >= 90:
            warnings.append(f"{label} kullanımı kritik seviyede: %{value:g}.")
            recommendations.append(recommendation)
            critical = True
        elif value >= 80:
            warnings.append(f"{label} kullanımı yüksek: %{value:g}.")
            recommendations.append(recommendation)

    temperatures = status.get("sicakliklar") or []
    hottest_temperature = max(
        (
            sensor.get("celsius")
            for sensor in temperatures
            if isinstance(sensor.get("celsius"), (int, float))
        ),
        default=None,
    )
    if hottest_temperature is not None:
        if hottest_temperature >= 95:
            warnings.append(f"Donanım sıcaklığı kritik seviyede: {hottest_temperature:g}°C.")
            recommendations.append(
                "Hava akışını ve soğutmayı kontrol et; yoğun işleri duraklatmayı düşün."
            )
            critical = True
        elif hottest_temperature >= 85:
            warnings.append(f"Donanım sıcaklığı yüksek: {hottest_temperature:g}°C.")
            recommendations.append("Soğutma ve hava akışını kontrol et.")

    unavailable_data = (
        ("surec_hatasi", "Süreç bilgisi"),
        ("ag_hatasi", "Ağ bilgisi"),
        ("uygulama_hatasi", "Açık uygulama bilgisi"),
        ("gecmis_hatasi", "Kaynak geçmişi"),
    )
    for key, label in unavailable_data:
        if status.get(key):
            data_notes.append(f"{label} alınamadı.")

    if critical:
        state, emoji = "Kritik", "🔴"
    elif warnings:
        state, emoji = "Dikkat", "🟠"
    elif data_notes:
        state, emoji = "Kısmi veri", "⚪"
    else:
        state, emoji = "İyi", "🟢"

    return {
        "durum": state,
        "emoji": emoji,
        "uyarilar": warnings,
        "oneriler": list(dict.fromkeys(recommendations)),
        "eksik_veriler": data_notes,
    }
