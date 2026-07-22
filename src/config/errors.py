"""설정 오류 형식."""


class ConfigError(ValueError):
    """사용자가 수정할 수 있는 설정 오류."""


class ConfigValidationError(ConfigError):
    """설정 스키마 또는 값 검증 실패."""


class DisabledConfigError(ConfigError):
    """실행이 승인되지 않은 설정을 사용하려는 경우."""
