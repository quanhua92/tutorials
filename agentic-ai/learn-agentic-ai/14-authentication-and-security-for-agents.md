# Authentication and Security for Agentic AI: Securing Autonomous Systems

**Based on:** [12_enterprise_security](https://github.com/panaversity/learn-agentic-ai/tree/bd868a5030d29df4d816c9d6322899655424b49a/12_enterprise_security)

## The Core Concept: Why This Example Exists

### The Problem: Traditional Security Models Don't Address Agent Autonomy

Traditional application security was designed for **human-operated systems** where users authenticate once and perform actions under direct supervision. Autonomous AI agents introduce unique security challenges:

- **Long-Running Operations**: Agents operate continuously without human presence
- **Cross-System Integration**: Agents access multiple APIs and services autonomously
- **Agent-to-Agent Communication**: Machines authenticating and authorizing other machines
- **Dynamic Capability Discovery**: Agents discover and use new services at runtime
- **Sensitive Data Processing**: Agents handle confidential information without human oversight
- **Multi-Tenant Environments**: Multiple agents sharing infrastructure with isolation requirements

The fundamental challenge is creating **security frameworks that protect sensitive systems while enabling the autonomous operation that makes agents valuable.**

### The Solution: Agent-Native Security Architecture

**Agent-native security** addresses these challenges through specialized patterns designed for autonomous systems:

- **Multi-Method Authentication**: Supporting OAuth 2.0, JWT, API keys, and mTLS for different scenarios
- **Agent Identity Management**: Cryptographic identities for autonomous systems
- **Permission-Based Authorization**: Fine-grained control over agent capabilities
- **Secure Agent Communication**: Standardized protocols for agent-to-agent trust
- **Continuous Security Monitoring**: Real-time detection of security anomalies
- **Zero-Trust Architecture**: Never trust, always verify—even for autonomous agents

The key insight: **Security for autonomous agents requires treating agents as both users and services simultaneously, with authentication patterns that support both human oversight and autonomous operation.**

---

## Practical Walkthrough: Code Breakdown

### Foundation Layer: Agent Identity and Authentication

Agent systems require robust identity management that supports both human authentication and machine-to-machine communication.

#### Agent Authentication Provider

**Multi-Method Authentication System:**
```python
from typing import Dict, List, Optional, Any
from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
import aiohttp
import asyncio
from datetime import datetime, timedelta
import secrets
import hashlib

class AgentAuthenticationProvider:
    """Comprehensive authentication provider for agent systems"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.jwt_secret = config.get("jwt_secret", secrets.token_urlsafe(32))
        self.oauth_providers = config.get("oauth_providers", {})
        self.api_keys = {}  # In production, use secure storage
        self.agent_sessions = {}
        
        # Initialize security schemes
        self.bearer_scheme = HTTPBearer()
        
    async def authenticate_human_user(
        self, 
        username: str, 
        password: str
    ) -> Optional[Dict[str, Any]]:
        """Authenticate human users with username/password"""
        
        # In production, verify against secure user store
        if await self._verify_user_credentials(username, password):
            user_claims = {
                "sub": username,
                "user_type": "human",
                "permissions": await self._get_user_permissions(username),
                "exp": datetime.utcnow() + timedelta(hours=8),
                "iat": datetime.utcnow(),
                "iss": "agent-auth-system"
            }
            
            token = jwt.encode(user_claims, self.jwt_secret, algorithm="HS256")
            
            return {
                "access_token": token,
                "token_type": "bearer",
                "expires_in": 28800,  # 8 hours
                "user_type": "human",
                "permissions": user_claims["permissions"]
            }
        
        return None
    
    async def authenticate_agent_oauth2(
        self,
        client_id: str,
        client_secret: str,
        scopes: List[str]
    ) -> Optional[Dict[str, Any]]:
        """Authenticate agents using OAuth 2.0 Client Credentials flow"""
        
        # Verify client credentials
        if not await self._verify_agent_credentials(client_id, client_secret):
            raise HTTPException(status_code=401, detail="Invalid client credentials")
        
        # Get agent information
        agent_info = await self._get_agent_info(client_id)
        
        # Validate requested scopes
        allowed_scopes = agent_info.get("allowed_scopes", [])
        validated_scopes = [scope for scope in scopes if scope in allowed_scopes]
        
        if not validated_scopes:
            raise HTTPException(status_code=400, detail="No valid scopes requested")
        
        # Create agent token
        agent_claims = {
            "sub": client_id,
            "user_type": "agent",
            "agent_id": client_id,
            "agent_name": agent_info.get("name"),
            "scopes": validated_scopes,
            "capabilities": agent_info.get("capabilities", []),
            "exp": datetime.utcnow() + timedelta(hours=24),  # Longer for agents
            "iat": datetime.utcnow(),
            "iss": "agent-auth-system",
            "aud": "agent-ecosystem"
        }
        
        token = jwt.encode(agent_claims, self.jwt_secret, algorithm="HS256")
        
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": 86400,  # 24 hours
            "scope": " ".join(validated_scopes),
            "user_type": "agent",
            "agent_id": client_id
        }
    
    async def authenticate_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """Authenticate using API key"""
        
        # Hash the key for lookup (keys should be stored hashed)
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        key_info = await self._get_api_key_info(key_hash)
        
        if key_info and key_info.get("active", False):
            # Check expiration
            if key_info.get("expires_at"):
                expires_at = datetime.fromisoformat(key_info["expires_at"])
                if datetime.utcnow() > expires_at:
                    raise HTTPException(status_code=401, detail="API key expired")
            
            # Create claims for API key authentication
            claims = {
                "sub": key_info["owner"],
                "user_type": "service",
                "api_key_id": key_info["key_id"],
                "permissions": key_info.get("permissions", []),
                "rate_limit": key_info.get("rate_limit", 1000),
                "exp": datetime.utcnow() + timedelta(hours=1),  # Short-lived
                "iat": datetime.utcnow(),
                "iss": "agent-auth-system"
            }
            
            return {
                "user_type": "service",
                "permissions": claims["permissions"],
                "rate_limit": claims["rate_limit"],
                "claims": claims
            }
        
        return None
    
    async def validate_bearer_token(
        self, 
        credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())
    ) -> Dict[str, Any]:
        """Validate JWT bearer token"""
        
        try:
            # Decode and validate JWT
            payload = jwt.decode(
                credentials.credentials,
                self.jwt_secret,
                algorithms=["HS256"],
                audience=["agent-ecosystem", None],  # Allow multiple audiences
                verify_exp=True
            )
            
            # Additional validation for agent tokens
            if payload.get("user_type") == "agent":
                agent_id = payload.get("agent_id")
                
                # Verify agent is still active and authorized
                if not await self._verify_agent_active(agent_id):
                    raise HTTPException(status_code=401, detail="Agent no longer authorized")
                
                # Check scope-based permissions
                required_scope = getattr(credentials, 'required_scope', None)
                if required_scope:
                    agent_scopes = payload.get("scopes", [])
                    if required_scope not in agent_scopes:
                        raise HTTPException(
                            status_code=403, 
                            detail=f"Insufficient scope. Required: {required_scope}"
                        )
            
            return payload
            
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")
    
    async def _verify_user_credentials(self, username: str, password: str) -> bool:
        """Verify user credentials against secure store"""
        # In production, use bcrypt/scrypt for password hashing
        # and verify against secure database
        return username == "admin" and password == "secure_password"  # Simplified
    
    async def _verify_agent_credentials(self, client_id: str, client_secret: str) -> bool:
        """Verify agent client credentials"""
        # In production, verify against secure agent registry
        agent_info = await self._get_agent_info(client_id)
        if agent_info:
            stored_secret = agent_info.get("client_secret_hash")
            secret_hash = hashlib.sha256(client_secret.encode()).hexdigest()
            return secrets.compare_digest(stored_secret, secret_hash)
        return False
    
    async def _get_agent_info(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Get agent information from registry"""
        # In production, query secure agent registry
        agent_registry = {
            "research-agent-001": {
                "name": "Research Agent",
                "client_secret_hash": hashlib.sha256("agent_secret_123".encode()).hexdigest(),
                "allowed_scopes": ["agent:read", "agent:write", "tools:execute"],
                "capabilities": ["web_search", "document_analysis", "report_generation"],
                "active": True
            }
        }
        
        return agent_registry.get(client_id)
    
    async def _get_user_permissions(self, username: str) -> List[str]:
        """Get user permissions"""
        # In production, query user permission system
        user_permissions = {
            "admin": ["agent:manage", "system:admin", "user:manage"],
            "operator": ["agent:monitor", "agent:interact"],
            "viewer": ["agent:view"]
        }
        
        return user_permissions.get(username, ["agent:view"])
    
    async def _verify_agent_active(self, agent_id: str) -> bool:
        """Verify agent is still active and authorized"""
        agent_info = await self._get_agent_info(agent_id)
        return agent_info and agent_info.get("active", False)

# Dependency for route protection
async def require_agent_auth(
    request: Request,
    auth_provider: AgentAuthenticationProvider = Depends(),
    required_scope: str = None
) -> Dict[str, Any]:
    """Require agent authentication with optional scope validation"""
    
    auth_header = request.headers.get("authorization")
    
    if not auth_header:
        raise HTTPException(status_code=401, detail="Authorization header required")
    
    if auth_header.startswith("Bearer "):
        # JWT token authentication
        from fastapi.security import HTTPAuthorizationCredentials
        credentials = HTTPAuthorizationCredentials(
            scheme="bearer",
            credentials=auth_header[7:]
        )
        credentials.required_scope = required_scope
        
        return await auth_provider.validate_bearer_token(credentials)
        
    elif auth_header.startswith("ApiKey "):
        # API key authentication
        api_key = auth_header[7:]
        auth_result = await auth_provider.authenticate_api_key(api_key)
        
        if not auth_result:
            raise HTTPException(status_code=401, detail="Invalid API key")
        
        return auth_result
    
    else:
        raise HTTPException(status_code=401, detail="Unsupported authentication method")
```

### Security Middleware Layer: Request and Response Protection

Security middleware provides centralized protection for all agent communications.

#### Comprehensive Security Middleware

**Request/Response Security Processing:**
```python
from fastapi import FastAPI, Request, Response
from fastapi.middleware.base import BaseHTTPMiddleware
import time
import logging
from typing import Dict, Any
import asyncio

class AgentSecurityMiddleware(BaseHTTPMiddleware):
    """Comprehensive security middleware for agent systems"""
    
    def __init__(
        self,
        app: FastAPI,
        auth_provider: AgentAuthenticationProvider,
        config: Dict[str, Any] = None
    ):
        super().__init__(app)
        self.auth_provider = auth_provider
        self.config = config or {}
        
        # Rate limiting
        self.rate_limits = {}
        self.rate_limit_window = 60  # 1 minute
        self.default_rate_limit = 100  # requests per minute
        
        # Security logging
        self.security_logger = logging.getLogger("agent_security")
        
        # Blocked IPs and agents
        self.blocked_ips = set()
        self.blocked_agents = set()
        
    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request through security layers"""
        
        start_time = time.time()
        client_ip = self._get_client_ip(request)
        
        try:
            # Security Layer 1: IP and Agent Blocking
            if await self._is_blocked(request, client_ip):
                return await self._create_blocked_response()
            
            # Security Layer 2: Rate Limiting
            if not await self._check_rate_limit(request, client_ip):
                return await self._create_rate_limit_response()
            
            # Security Layer 3: Authentication Validation
            auth_context = await self._validate_authentication(request)
            
            # Security Layer 4: Authorization Check
            if not await self._check_authorization(request, auth_context):
                return await self._create_unauthorized_response()
            
            # Security Layer 5: Request Validation
            if not await self._validate_request(request):
                return await self._create_bad_request_response()
            
            # Add security context to request
            request.state.auth_context = auth_context
            request.state.security_validated = True
            
            # Process the request
            response = await call_next(request)
            
            # Security Layer 6: Response Processing
            response = await self._process_response(request, response)
            
            # Log successful request
            await self._log_security_event(
                "request_success",
                request,
                auth_context,
                {"processing_time": time.time() - start_time}
            )
            
            return response
            
        except Exception as e:
            # Log security exception
            await self._log_security_event(
                "security_error",
                request,
                None,
                {"error": str(e), "processing_time": time.time() - start_time}
            )
            
            # Return generic error response (don't leak information)
            return await self._create_error_response()
    
    async def _is_blocked(self, request: Request, client_ip: str) -> bool:
        """Check if IP or agent is blocked"""
        
        # Check IP blocking
        if client_ip in self.blocked_ips:
            await self._log_security_event("blocked_ip_attempt", request, None, {"ip": client_ip})
            return True
        
        # Check agent blocking (from auth header)
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                # Decode without verification to get agent ID
                token = auth_header[7:]
                payload = jwt.decode(token, options={"verify_signature": False})
                agent_id = payload.get("agent_id")
                
                if agent_id and agent_id in self.blocked_agents:
                    await self._log_security_event(
                        "blocked_agent_attempt", 
                        request, 
                        None, 
                        {"agent_id": agent_id}
                    )
                    return True
            except:
                pass  # Invalid token, will be caught in auth validation
        
        return False
    
    async def _check_rate_limit(self, request: Request, client_ip: str) -> bool:
        """Check rate limiting"""
        
        current_time = time.time()
        window_start = current_time - self.rate_limit_window
        
        # Get rate limit key (IP or agent ID)
        rate_limit_key = client_ip
        
        # Try to get agent-specific rate limit
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                token = auth_header[7:]
                payload = jwt.decode(token, options={"verify_signature": False})
                agent_id = payload.get("agent_id")
                if agent_id:
                    rate_limit_key = f"agent:{agent_id}"
            except:
                pass
        
        # Initialize rate limit tracking
        if rate_limit_key not in self.rate_limits:
            self.rate_limits[rate_limit_key] = []
        
        # Clean old requests
        self.rate_limits[rate_limit_key] = [
            req_time for req_time in self.rate_limits[rate_limit_key]
            if req_time > window_start
        ]
        
        # Check current request count
        current_requests = len(self.rate_limits[rate_limit_key])
        rate_limit = self._get_rate_limit_for_key(rate_limit_key)
        
        if current_requests >= rate_limit:
            await self._log_security_event(
                "rate_limit_exceeded",
                request,
                None,
                {"key": rate_limit_key, "count": current_requests, "limit": rate_limit}
            )
            return False
        
        # Add current request
        self.rate_limits[rate_limit_key].append(current_time)
        return True
    
    def _get_rate_limit_for_key(self, key: str) -> int:
        """Get rate limit for specific key"""
        if key.startswith("agent:"):
            # Agents may have higher rate limits
            return 500
        else:
            # Default rate limit for IPs
            return self.default_rate_limit
    
    async def _validate_authentication(self, request: Request) -> Optional[Dict[str, Any]]:
        """Validate request authentication"""
        
        # Skip auth for public endpoints
        if self._is_public_endpoint(request.url.path):
            return {"user_type": "anonymous", "permissions": ["public:read"]}
        
        auth_header = request.headers.get("authorization")
        
        if not auth_header:
            # Check if endpoint requires auth
            if self._requires_authentication(request.url.path):
                raise HTTPException(status_code=401, detail="Authentication required")
            return {"user_type": "anonymous", "permissions": []}
        
        try:
            # Delegate to auth provider
            if auth_header.startswith("Bearer "):
                from fastapi.security import HTTPAuthorizationCredentials
                credentials = HTTPAuthorizationCredentials(
                    scheme="bearer",
                    credentials=auth_header[7:]
                )
                return await self.auth_provider.validate_bearer_token(credentials)
                
            elif auth_header.startswith("ApiKey "):
                api_key = auth_header[7:]
                return await self.auth_provider.authenticate_api_key(api_key)
            
            else:
                raise HTTPException(status_code=401, detail="Unsupported auth method")
                
        except HTTPException:
            raise
        except Exception as e:
            await self._log_security_event(
                "auth_validation_error",
                request,
                None,
                {"error": str(e)}
            )
            raise HTTPException(status_code=401, detail="Authentication failed")
    
    async def _check_authorization(self, request: Request, auth_context: Dict[str, Any]) -> bool:
        """Check if authenticated user/agent is authorized for this request"""
        
        if not auth_context:
            return False
        
        # Get required permissions for this endpoint
        required_permissions = self._get_required_permissions(request.url.path, request.method)
        
        if not required_permissions:
            return True  # No specific permissions required
        
        # Check user/agent permissions
        user_permissions = auth_context.get("permissions", [])
        user_scopes = auth_context.get("scopes", [])
        
        # Check if any required permission is satisfied
        for req_perm in required_permissions:
            if req_perm in user_permissions or req_perm in user_scopes:
                return True
        
        # Log authorization failure
        await self._log_security_event(
            "authorization_denied",
            request,
            auth_context,
            {
                "required_permissions": required_permissions,
                "user_permissions": user_permissions,
                "user_scopes": user_scopes
            }
        )
        
        return False
    
    async def _validate_request(self, request: Request) -> bool:
        """Validate request for security issues"""
        
        # Check request size
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 10 * 1024 * 1024:  # 10MB limit
            await self._log_security_event("large_request_blocked", request, None, {
                "content_length": content_length
            })
            return False
        
        # Check for suspicious headers
        suspicious_headers = ["x-forwarded-host", "x-real-ip"]
        for header in suspicious_headers:
            if header in request.headers:
                header_value = request.headers[header]
                if not self._is_valid_header_value(header_value):
                    await self._log_security_event("suspicious_header", request, None, {
                        "header": header,
                        "value": header_value
                    })
                    return False
        
        # Validate URL path
        if not self._is_valid_path(request.url.path):
            await self._log_security_event("invalid_path", request, None, {
                "path": request.url.path
            })
            return False
        
        return True
    
    async def _process_response(self, request: Request, response: Response) -> Response:
        """Process response for security"""
        
        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        # Remove sensitive headers
        sensitive_headers = ["server", "x-powered-by"]
        for header in sensitive_headers:
            if header in response.headers:
                del response.headers[header]
        
        # Add agent-specific security headers
        if hasattr(request.state, "auth_context"):
            auth_context = request.state.auth_context
            if auth_context.get("user_type") == "agent":
                response.headers["X-Agent-Security"] = "validated"
                response.headers["X-Agent-ID"] = auth_context.get("agent_id", "unknown")
        
        return response
    
    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address"""
        # Check for forwarded headers (behind proxy)
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
        
        # Fallback to direct connection
        return request.client.host if request.client else "unknown"
    
    def _is_public_endpoint(self, path: str) -> bool:
        """Check if endpoint is public (no auth required)"""
        public_paths = ["/health", "/metrics", "/docs", "/openapi.json", "/.well-known/"]
        return any(path.startswith(public_path) for public_path in public_paths)
    
    def _requires_authentication(self, path: str) -> bool:
        """Check if endpoint requires authentication"""
        # Most agent endpoints require authentication
        return path.startswith("/a2a/") or path.startswith("/agents/")
    
    def _get_required_permissions(self, path: str, method: str) -> List[str]:
        """Get required permissions for endpoint"""
        # Define permission mapping
        permission_map = {
            "/a2a/execute": ["agent:execute"],
            "/agents/*/chat": ["agent:interact"],
            "/agents/*/status": ["agent:monitor"],
            "/admin/*": ["system:admin"]
        }
        
        # Find matching pattern
        for pattern, permissions in permission_map.items():
            if self._path_matches_pattern(path, pattern):
                return permissions
        
        return []
    
    def _path_matches_pattern(self, path: str, pattern: str) -> bool:
        """Check if path matches permission pattern"""
        # Simple pattern matching (in production, use more sophisticated routing)
        if "*" in pattern:
            prefix = pattern.split("*")[0]
            return path.startswith(prefix)
        return path == pattern
    
    async def _log_security_event(
        self,
        event_type: str,
        request: Request,
        auth_context: Optional[Dict[str, Any]],
        details: Dict[str, Any]
    ):
        """Log security events for monitoring and auditing"""
        
        event_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "client_ip": self._get_client_ip(request),
            "user_agent": request.headers.get("user-agent"),
            "path": request.url.path,
            "method": request.method,
            "auth_context": auth_context,
            "details": details
        }
        
        # Log to structured logger
        self.security_logger.info(f"Security event: {event_type}", extra=event_data)
        
        # In production, also send to SIEM/monitoring system
        await self._send_to_monitoring_system(event_data)
    
    async def _send_to_monitoring_system(self, event_data: Dict[str, Any]):
        """Send security events to monitoring system"""
        # In production, send to OpenTelemetry, Prometheus, or SIEM
        pass
    
    # Response helper methods
    async def _create_blocked_response(self) -> Response:
        return Response(
            content='{"error": "Access denied"}',
            status_code=403,
            media_type="application/json"
        )
    
    async def _create_rate_limit_response(self) -> Response:
        return Response(
            content='{"error": "Rate limit exceeded"}',
            status_code=429,
            media_type="application/json",
            headers={"Retry-After": "60"}
        )
    
    async def _create_unauthorized_response(self) -> Response:
        return Response(
            content='{"error": "Unauthorized"}',
            status_code=401,
            media_type="application/json"
        )
    
    async def _create_bad_request_response(self) -> Response:
        return Response(
            content='{"error": "Bad request"}',
            status_code=400,
            media_type="application/json"
        )
    
    async def _create_error_response(self) -> Response:
        return Response(
            content='{"error": "Internal server error"}',
            status_code=500,
            media_type="application/json"
        )
```

### Agent-to-Agent Security Layer: A2A Protocol Security

Secure communication between autonomous agents requires specialized protocols and trust mechanisms.

#### A2A Security Implementation

**Secure Agent Communication Protocol:**
```python
import aiohttp
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
import base64
import json

class A2ASecurityManager:
    """Security manager for Agent-to-Agent communication"""
    
    def __init__(self, agent_id: str, private_key: bytes = None):
        self.agent_id = agent_id
        
        # Generate or load RSA key pair for this agent
        if private_key:
            self.private_key = serialization.load_pem_private_key(private_key, password=None)
        else:
            self.private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048
            )
        
        self.public_key = self.private_key.public_key()
        
        # Trusted agent registry
        self.trusted_agents = {}
        self.agent_certificates = {}
        
    async def register_trusted_agent(
        self, 
        agent_id: str, 
        public_key_pem: bytes,
        certificate: Dict[str, Any] = None
    ):
        """Register a trusted agent's public key"""
        
        try:
            public_key = serialization.load_pem_public_key(public_key_pem)
            self.trusted_agents[agent_id] = public_key
            
            if certificate:
                # Verify certificate signature and store
                if await self._verify_agent_certificate(certificate):
                    self.agent_certificates[agent_id] = certificate
                    print(f"✅ Registered trusted agent: {agent_id}")
                else:
                    print(f"❌ Invalid certificate for agent: {agent_id}")
                    
        except Exception as e:
            print(f"Error registering agent {agent_id}: {e}")
    
    async def create_secure_request(
        self,
        target_agent_id: str,
        method: str,
        payload: Dict[str, Any],
        encrypt: bool = True
    ) -> Dict[str, Any]:
        """Create a secure request to another agent"""
        
        if target_agent_id not in self.trusted_agents:
            raise Exception(f"Agent {target_agent_id} not in trusted agents list")
        
        # Create request structure
        request_data = {
            "jsonrpc": "2.0",
            "id": self._generate_request_id(),
            "method": method,
            "params": payload,
            "metadata": {
                "source_agent": self.agent_id,
                "target_agent": target_agent_id,
                "timestamp": datetime.utcnow().isoformat(),
                "security_level": "encrypted" if encrypt else "signed"
            }
        }
        
        # Sign the request
        signature = await self._sign_request(request_data)
        request_data["signature"] = signature
        
        # Encrypt if requested
        if encrypt:
            encrypted_payload = await self._encrypt_for_agent(
                json.dumps(payload).encode(),
                target_agent_id
            )
            request_data["params"] = {"encrypted_data": encrypted_payload}
            request_data["metadata"]["encrypted"] = True
        
        return request_data
    
    async def verify_secure_request(
        self,
        request_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Verify a secure request from another agent"""
        
        source_agent = request_data.get("metadata", {}).get("source_agent")
        
        if not source_agent or source_agent not in self.trusted_agents:
            raise Exception(f"Untrusted source agent: {source_agent}")
        
        # Verify signature
        if not await self._verify_request_signature(request_data, source_agent):
            raise Exception("Request signature verification failed")
        
        # Decrypt if encrypted
        if request_data.get("metadata", {}).get("encrypted"):
            encrypted_data = request_data["params"]["encrypted_data"]
            decrypted_payload = await self._decrypt_from_agent(
                encrypted_data,
                source_agent
            )
            request_data["params"] = json.loads(decrypted_payload.decode())
        
        # Verify timestamp (prevent replay attacks)
        timestamp_str = request_data.get("metadata", {}).get("timestamp")
        if timestamp_str:
            request_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            time_diff = datetime.utcnow() - request_time.replace(tzinfo=None)
            
            if time_diff.total_seconds() > 300:  # 5 minutes
                raise Exception("Request timestamp too old (possible replay attack)")
        
        return request_data
    
    async def _sign_request(self, request_data: Dict[str, Any]) -> str:
        """Sign request with agent's private key"""
        
        # Create canonical representation for signing
        signing_data = {
            "method": request_data["method"],
            "params": request_data["params"],
            "metadata": request_data["metadata"]
        }
        
        canonical_data = json.dumps(signing_data, sort_keys=True)
        
        # Sign with RSA-PSS
        signature = self.private_key.sign(
            canonical_data.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        
        return base64.b64encode(signature).decode()
    
    async def _verify_request_signature(
        self, 
        request_data: Dict[str, Any], 
        source_agent: str
    ) -> bool:
        """Verify request signature"""
        
        try:
            signature_b64 = request_data.get("signature")
            if not signature_b64:
                return False
            
            signature = base64.b64decode(signature_b64)
            
            # Recreate canonical data
            signing_data = {
                "method": request_data["method"],
                "params": request_data["params"],
                "metadata": request_data["metadata"]
            }
            canonical_data = json.dumps(signing_data, sort_keys=True)
            
            # Verify signature
            public_key = self.trusted_agents[source_agent]
            public_key.verify(
                signature,
                canonical_data.encode(),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            return True
            
        except Exception as e:
            print(f"Signature verification failed: {e}")
            return False
    
    async def _encrypt_for_agent(self, data: bytes, target_agent_id: str) -> str:
        """Encrypt data for specific agent"""
        
        target_public_key = self.trusted_agents[target_agent_id]
        
        # Generate symmetric key for data encryption
        symmetric_key = Fernet.generate_key()
        fernet = Fernet(symmetric_key)
        
        # Encrypt data with symmetric key
        encrypted_data = fernet.encrypt(data)
        
        # Encrypt symmetric key with target's public key
        encrypted_key = target_public_key.encrypt(
            symmetric_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        
        # Combine encrypted key and data
        combined = {
            "encrypted_key": base64.b64encode(encrypted_key).decode(),
            "encrypted_data": base64.b64encode(encrypted_data).decode()
        }
        
        return base64.b64encode(json.dumps(combined).encode()).decode()
    
    async def _decrypt_from_agent(self, encrypted_payload: str, source_agent: str) -> bytes:
        """Decrypt data from specific agent"""
        
        try:
            # Decode the payload
            combined_data = json.loads(base64.b64decode(encrypted_payload).decode())
            
            encrypted_key = base64.b64decode(combined_data["encrypted_key"])
            encrypted_data = base64.b64decode(combined_data["encrypted_data"])
            
            # Decrypt symmetric key with our private key
            symmetric_key = self.private_key.decrypt(
                encrypted_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            
            # Decrypt data with symmetric key
            fernet = Fernet(symmetric_key)
            decrypted_data = fernet.decrypt(encrypted_data)
            
            return decrypted_data
            
        except Exception as e:
            raise Exception(f"Decryption failed: {e}")
    
    def _generate_request_id(self) -> str:
        """Generate unique request ID"""
        import uuid
        return str(uuid.uuid4())
    
    async def _verify_agent_certificate(self, certificate: Dict[str, Any]) -> bool:
        """Verify agent certificate (simplified)"""
        # In production, verify against certificate authority
        required_fields = ["agent_id", "public_key", "issued_by", "expires_at"]
        return all(field in certificate for field in required_fields)

# Usage in FastAPI application
class SecureAgentAPI:
    """Secure API for agent communication"""
    
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.security_manager = A2ASecurityManager(agent_id)
        self.auth_provider = AgentAuthenticationProvider({
            "jwt_secret": "your-secret-key"
        })
        
    async def setup_security(self, app: FastAPI):
        """Set up security for FastAPI application"""
        
        # Add security middleware
        app.add_middleware(
            AgentSecurityMiddleware,
            auth_provider=self.auth_provider,
            config={"enable_rate_limiting": True}
        )
        
        # OAuth 2.0 token endpoint
        @app.post("/auth/token")
        async def get_access_token(
            grant_type: str,
            client_id: str,
            client_secret: str,
            scope: str = ""
        ):
            """OAuth 2.0 token endpoint for agents"""
            
            if grant_type != "client_credentials":
                raise HTTPException(status_code=400, detail="Unsupported grant type")
            
            scopes = scope.split() if scope else []
            
            token_data = await self.auth_provider.authenticate_agent_oauth2(
                client_id, client_secret, scopes
            )
            
            if not token_data:
                raise HTTPException(status_code=401, detail="Invalid credentials")
            
            return token_data
        
        # Secure A2A endpoint
        @app.post("/a2a/execute")
        async def execute_a2a_request(
            request: Request,
            auth_context: Dict[str, Any] = Depends(require_agent_auth)
        ):
            """Execute secure agent-to-agent request"""
            
            # Verify this is an agent making the request
            if auth_context.get("user_type") != "agent":
                raise HTTPException(status_code=403, detail="Agent authentication required")
            
            # Get request data
            request_data = await request.json()
            
            # Verify secure request
            try:
                verified_request = await self.security_manager.verify_secure_request(request_data)
                
                # Process the request
                result = await self._process_agent_request(verified_request)
                
                return {"status": "success", "result": result}
                
            except Exception as e:
                await self._log_security_violation(
                    "a2a_verification_failed",
                    auth_context.get("agent_id"),
                    str(e)
                )
                raise HTTPException(status_code=400, detail="Invalid secure request")
    
    async def _process_agent_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process verified agent request"""
        method = request_data["method"]
        params = request_data["params"]
        
        # Route to appropriate handler
        if method == "execute_task":
            return await self._execute_task(params)
        elif method == "get_status":
            return await self._get_agent_status()
        else:
            raise Exception(f"Unknown method: {method}")
    
    async def _execute_task(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute task requested by another agent"""
        # Implementation depends on agent capabilities
        return {"status": "completed", "result": "task executed"}
    
    async def _get_agent_status(self) -> Dict[str, Any]:
        """Get current agent status"""
        return {
            "agent_id": self.agent_id,
            "status": "active",
            "load": 0.3,
            "available_capabilities": ["web_search", "analysis"]
        }
    
    async def _log_security_violation(self, violation_type: str, agent_id: str, details: str):
        """Log security violations for monitoring"""
        print(f"🚨 Security violation: {violation_type} by {agent_id}: {details}")

# Example usage
async def create_secure_agent_system():
    """Create a secure agent system"""
    
    app = FastAPI(title="Secure Agent API")
    
    # Create secure API
    secure_api = SecureAgentAPI("secure-agent-001")
    await secure_api.setup_security(app)
    
    print("🔒 Secure agent system initialized")
    return app
```

---

## Mental Model: Thinking Zero-Trust for Agents

### Build the Mental Model: Security as Autonomy Enabler

Think of agent security like **airport security**—not as a barrier, but as the system that enables safe operation:

**Traditional Security (Perimeter-Based)**:
- **Trust the network**: Once inside, everything is trusted
- **Static rules**: Same security for all users
- **Human oversight**: Assumes human decision-making

**Agent Security (Zero-Trust)**:
- **Never trust, always verify**: Even internal agents are validated
- **Dynamic authorization**: Permissions based on context and behavior
- **Autonomous operation**: Security that works without human intervention

### Why It's Designed This Way: Supporting Autonomous Operation

Agent security must balance protection with autonomy:

1. **Continuous Verification**: Authentication that works for long-running operations
2. **Fine-Grained Authorization**: Precise control over agent capabilities
3. **Transparent Monitoring**: Visibility into security events without hindering operation
4. **Adaptive Response**: Security that responds to threats without human intervention

### Further Exploration: Advanced Security Patterns

**Immediate Practice:**
1. Implement OAuth 2.0 authentication for agent systems
2. Create A2A secure communication between agents
3. Add comprehensive security middleware with rate limiting
4. Build security monitoring and alerting systems

**Design Challenge:**
Create a "zero-trust agent ecosystem" where:
- Every agent interaction is authenticated and authorized
- Security policies adapt based on agent behavior
- Threats are detected and mitigated automatically
- Compliance requirements are enforced continuously

**Advanced Exploration:**
- How would you implement behavioral biometrics for agent authentication?
- What patterns support security policy evolution without downtime?
- How could you create agent security reputation systems?
- What techniques enable privacy-preserving agent collaboration?

---

*Authentication and security for agentic AI systems require specialized patterns that support autonomous operation while maintaining human oversight and protection. Understanding these security frameworks is essential for building production-ready agent systems that can operate safely in enterprise environments while enabling the autonomous capabilities that make agents valuable.*