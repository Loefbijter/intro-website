class RegistrationError(Exception):
    """Base for registration failures that carry a Dutch, user-facing message."""

    def __init__(self, message):
        self.message = message
        super().__init__(message)


class DuplicateRegistration(RegistrationError):
    pass


class RegistrationClosed(RegistrationError):
    pass


class RegistrationNotAvailable(RegistrationError):
    """Activity doesn't use the standard registration flow at all."""


class RegistrationValidationError(RegistrationError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("Ongeldige inschrijving.")


class HoneypotTriggered(Exception):
    """Bot detected — caller should pretend success without persisting anything."""
