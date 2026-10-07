def test_application_package_is_importable():
    import app

    assert app.__package__ == "app"
