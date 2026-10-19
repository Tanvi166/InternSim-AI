from fastapi import Header, HTTPException
from typing import Optional
from database import get_supabase_client

def get_authenticated_user_id(authorization: Optional[str] = Header(None)) -> Optional[str]:
    """
    Validates the Supabase JWT token from the Authorization header (Bearer <token>).
    Returns the authenticated user's UUID if valid; returns None if no header is supplied.
    Raises HTTPException(401) if an invalid or expired token is provided.
    """
    if not authorization:
        return None
        
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header format. Expected 'Bearer <token>'.")
        
    token = parts[1]
    supabase = get_supabase_client()
    try:
        user_response = supabase.auth.get_user(token)
        if not user_response or not user_response.user or not user_response.user.id:
            raise HTTPException(status_code=401, detail="Invalid or expired authentication token.")
        return str(user_response.user.id)
    except HTTPException:
        raise
    except Exception as e:
        # Supabase API error on invalid JWT
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")
