# app/helpers/auth_gate.py
"""
Gate de autenticación (Supabase Auth) para apps Streamlit multipage.

IMPORTANTE — Streamlit multipage NO tiene middleware compartido: cada
archivo en `pages/` (y el entrypoint `home.py`) se sirve de forma
independiente. Un gate solo en `home.py` NO protege el resto — cualquiera
puede escribir la URL de una página directo en el navegador y saltarse
el login. `require_auth()` debe llamarse al inicio de CADA archivo de
página, inmediatamente después de `st.set_page_config(...)`.

Diseño en dos capas (deliberado — no fusionar):
    require_auth()          -> SOLO identidad: ¿quién es esta persona?
                                (Supabase Auth, ya implementado).
    require_plan(min_plan)  -> SOLO entitlement: ¿tiene acceso pagado?
                                (stub — lee profiles.plan; hoy siempre
                                deja pasar. Activar cuando exista el
                                paywall real, sin tocar require_auth()).

MVP invite-only: NO hay pantalla de registro público. Las cuentas se
crean manualmente en el dashboard de Supabase (Authentication > Users
> Add user) o vía Admin API con el service_role key — nunca desde esta
app, que solo usa el anon key.

Limitación conocida: la sesión vive en `st.session_state`, así que un
refresh duro del navegador cierra la sesión (hay que volver a loguearse).
Aceptable para demos guiadas de tamaño de pipeline actual (~54
prospectos). Si se vuelve molesto, la mejora es persistir el JWT en una
cookie de navegador (p.ej. `streamlit-cookies-controller`) en vez de
reescribir este módulo.

Variables de entorno requeridas (ver .env.example):
    SUPABASE_URL
    SUPABASE_ANON_KEY   — anon/public key. NUNCA el service_role key
                           aquí (ese solo vive server-side, p.ej. en un
                           script de administración de usuarios, jamás
                           en una app Streamlit desplegada).

Modo temporal de pruebas:
    LATTISE_AUTH_MODE=disabled

    Omite Supabase y crea una identidad local de prueba. No es el modo por
    defecto y debe retirarse del entorno antes de publicar la aplicación.
"""
from __future__ import annotations

import os

import streamlit as st

try:
    from supabase import Client, create_client
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Falta el paquete 'supabase' (pip install supabase). Ver requirements.txt."
    ) from exc


_AUTH_MODE_ENV = "LATTISE_AUTH_MODE"
_TEST_USER_EMAIL_ENV = "LATTISE_TEST_USER_EMAIL"
_ALLOWED_AUTH_MODES = {"supabase", "disabled"}


def _setting(name: str, default: str = "") -> str:
    """Lee primero el entorno y luego los secretos del despliegue Streamlit."""
    value = os.environ.get(name)
    if value is not None:
        return value
    try:
        return str(st.secrets.get(name, default))
    except (AttributeError, FileNotFoundError):
        return default


def _auth_mode() -> str:
    """Modo de acceso explícito; producción conserva Supabase por defecto."""
    mode = _setting(_AUTH_MODE_ENV, "supabase").strip().lower()
    if mode not in _ALLOWED_AUTH_MODES:
        raise RuntimeError(
            f"{_AUTH_MODE_ENV} debe ser uno de: {', '.join(sorted(_ALLOWED_AUTH_MODES))}."
        )
    return mode


def _test_user() -> dict:
    email = _setting(_TEST_USER_EMAIL_ENV, "tester@local.lattise").strip()
    return {"id": "local-testing-user", "email": email or "tester@local.lattise"}


@st.cache_resource(show_spinner=False)
def _get_client() -> "Client":
    url = _setting("SUPABASE_URL")
    key = _setting("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL / SUPABASE_ANON_KEY no configuradas. Ver .env.example "
            "y las variables de entorno del servicio en Railway."
        )
    return create_client(url, key)


def _render_login_form() -> None:
    st.markdown("### Iniciar sesión — Lattise Studio")
    st.caption(
        "Acceso solo por invitación. Si no tienes cuenta, contacta al equipo de Lattise."
    )
    with st.form("auth_login_form", clear_on_submit=False):
        email = st.text_input("Correo")
        password = st.text_input("Contraseña", type="password")
        submitted = st.form_submit_button("Entrar", type="primary", use_container_width=True)

    if not submitted:
        return

    if not email or not password:
        st.error("Ingresa correo y contraseña.")
        return

    client = _get_client()
    try:
        result = client.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as exc:
        st.error(f"No se pudo iniciar sesión: {exc}")
        return

    if result.user is None or result.session is None:
        st.error("Credenciales inválidas.")
        return

    st.session_state["auth_user"] = {"id": result.user.id, "email": result.user.email}
    st.session_state["auth_session"] = {
        "access_token": result.session.access_token,
        "refresh_token": result.session.refresh_token,
    }
    st.rerun()


def require_auth() -> dict:
    """
    Llamar al inicio de CADA archivo de página, justo después de
    `st.set_page_config(...)`. Si no hay sesión activa, renderiza el
    login y detiene el resto de la página (`st.stop()`) — el código
    debajo de esta llamada nunca se ejecuta sin sesión. Si hay sesión,
    devuelve `{"id": ..., "email": ...}` y la página continúa normal.
    """
    user = st.session_state.get("auth_user")
    if user is not None:
        return user

    if _auth_mode() == "disabled":
        user = _test_user()
        st.session_state["auth_user"] = user
        st.warning(
            "Modo de pruebas activo: el acceso no está protegido por autenticación. "
            "No usar esta configuración en producción.",
        )
        return user

    _render_login_form()
    st.stop()


def require_plan(min_plan: str = "beta") -> dict:
    """
    STUB para el paywall futuro. Hoy es equivalente a `require_auth()`
    — no bloquea por plan. Cuando exista la tabla `profiles` con la
    columna `plan` (ver migrations/001_profiles.sql), reemplazar el
    cuerpo por una consulta a esa tabla usando el `id` del usuario
    autenticado, sin cambiar la firma ni los call-sites.
    """
    return require_auth()


def render_logout_button(container=None) -> None:
    """Botón de logout opcional. Colocar típicamente en el sidebar de
    cada página, después de `require_auth()`."""
    user = st.session_state.get("auth_user")
    if user is None:
        return
    target = container if container is not None else st.sidebar
    with target:
        st.caption(f"Sesión: {user['email']}")
        if st.button("Cerrar sesión", key="auth_logout_btn", use_container_width=True):
            client = _get_client()
            try:
                client.auth.sign_out()
            except Exception:
                pass
            for k in ("auth_user", "auth_session"):
                st.session_state.pop(k, None)
            st.rerun()


__all__ = ["require_auth", "require_plan", "render_logout_button"]
