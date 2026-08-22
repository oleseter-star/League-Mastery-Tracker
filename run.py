from application.services.application_launcher_service import (
    ApplicationLauncherService,
)


def main():
    """
    Start League Mastery Tracker through the application launcher.
    """

    launcher = (
        ApplicationLauncherService()
    )

    return launcher.run()


if __name__ == "__main__":
    main()