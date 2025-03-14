from datetime import datetime, timedelta, timezone
import jwt
import streamlit as st
import utils  # your custom module for configuration and token management
import streamlit.components.v1 as components

# Define UTC timezone
UTC = timezone.utc

# Set page title and header
st.set_page_config(page_title="Luminai App - File Upload")
st.title("Luminai App - File Upload")

# Configure Cognito OAuth component
oauth2 = utils.configure_oauth_component()

# If no token in session, show the Cognito login button
if "token" not in st.session_state:
    redirect_uri = f"https://{utils.OAUTH_CONFIG['ExternalDns']}/component/streamlit_oauth.authorize_button/index.html"
    result = oauth2.authorize_button("Connect with Cognito", scope="openid", pkce="S256", redirect_uri=redirect_uri)
    if result and "token" in result:
        st.session_state.token = result.get("token")
        # Retrieve and set the Identity Center token with its expiration
        st.session_state["idc_jwt_token"] = utils.get_iam_oidc_token(st.session_state.token["id_token"])
        st.session_state["idc_jwt_token"]["expires_at"] = datetime.now(tz=UTC) + timedelta(seconds=st.session_state["idc_jwt_token"]["expiresIn"])
        st.experimental_rerun()
else:
    # User is authenticated
    token = st.session_state["token"]
    user_email = jwt.decode(token["id_token"], options={"verify_signature": False}).get("email", "User")
    
    # Display a welcome message and refresh button (if needed)
    st.write(f"Welcome, {user_email}!")
    if st.button("Refresh Cognito Token"):
        refresh_token = token["refresh_token"]
        token = oauth2.refresh_token(token, force=True)
        token["refresh_token"] = refresh_token  # Keep the refresh token
        st.session_state.token = token
        st.experimental_rerun()

    # (Optional) Refresh Identity Center token if expired
    if "idc_jwt_token" not in st.session_state:
        st.session_state["idc_jwt_token"] = utils.get_iam_oidc_token(token["id_token"])
        st.session_state["idc_jwt_token"]["expires_at"] = datetime.now(tz=UTC) + timedelta(seconds=st.session_state["idc_jwt_token"]["expiresIn"])
    elif st.session_state["idc_jwt_token"]["expires_at"] < datetime.now(tz=UTC):
        try:
            st.session_state["idc_jwt_token"] = utils.refresh_iam_oidc_token(st.session_state["idc_jwt_token"]["refreshToken"])
            st.session_state["idc_jwt_token"]["expires_at"] = datetime.now(tz=UTC) + timedelta(seconds=st.session_state["idc_jwt_token"]["expiresIn"])
        except Exception as e:
            st.error(f"Error refreshing Identity Center token: {e}. Please reload the page.")

    # Embed the Uppy file uploader via an iframe
    # Replace the URL below with the actual URL where your Uppy/React uploader is hosted.
    uploader_url = "https://your-upload-app-domain"  
    components.html(
        f'<iframe src="https://staging.d1cnh47nde9q6x.amplifyapp.com" width="100%" height="600" frameborder="0"></iframe>',
        height=600,
    )