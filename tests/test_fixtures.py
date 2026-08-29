def test_shared_fixtures_cover_report_and_pushplus(
    settings,
    report,
    snapshot_store,
    pushplus_adapter,
) -> None:
    assert settings.push_channels == ["pushplus"]
    assert report.title == "上海日报 · 2026-08-29"
    assert snapshot_store.has_report_for_date("2026-08-29") is False

    result = pushplus_adapter.send_report(report)

    assert result.success is True
    assert result.channel == "pushplus"
