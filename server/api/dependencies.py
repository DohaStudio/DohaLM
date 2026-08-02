"""Typed access to application-lifetime server resources."""

import logging

from fastapi import Request

from server.core.config import APISettings
from server.services.inference import InferenceService
from src.inference import ProviderRegistry


def get_settings(request: Request) -> APISettings:
    return request.app.state.settings


def get_registry(request: Request) -> ProviderRegistry:
    return request.app.state.provider_registry


def get_inference_service(request: Request) -> InferenceService:
    return request.app.state.inference_service


def get_request_id(request: Request) -> str:
    return request.state.request_id


def get_logger(request: Request) -> logging.Logger:
    return request.app.state.logger
