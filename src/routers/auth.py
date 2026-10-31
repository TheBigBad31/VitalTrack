"""Routeur FastAPI pour l'authentification et la gestion des utilisateurs."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from typing import Optional

from src.app import app, db, AuthUser
from src.auth import (
    AuthUser, GoogleAuthPayload, LoginRequest, RegisterRequest,
    create_access_token, decode_access_token, hash_password,
    parse_google_identity, verify_password
)
from src.models import UserConsentItem
from src.routers.friends import verify_view_access

router = APIRouter(prefix="/api/auth", tags=["auth"])