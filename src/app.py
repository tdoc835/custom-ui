from datetime import datetime, timedelta, timezone

import jwt
import jwt.algorithms
import streamlit as st  #all streamlit commands will be available through the "st" alias
import utils
from streamlit_feedback import streamlit_feedback
import boto3
from botocore.exceptions import ClientError

UTC=timezone.utc

# Init configuration
utils.retrieve_config_from_agent()
if "aws_credentials" not in st.session_state:
    st.session_state.aws_credentials = None

st.set_page_config(page_title="Luminai App") #HTML title
st.title("Luminai App") #page title

# Define a function to clear the chat history
def clear_chat_history():
    st.session_state.messages = [{"role": "assistant", "content": "How may I assist you today?"}]
    st.session_state.questions = []
    st.session_state.answers = []
    st.session_state.input = ""
    st.session_state["chat_history"] = []
    st.session_state["conversationId"] = ""
    st.session_state["parentMessageId"] = ""


oauth2 = utils.configure_oauth_component()
if "token" not in st.session_state:
    # If not, show authorize button
    redirect_uri = f"https://{utils.OAUTH_CONFIG['ExternalDns']}/component/streamlit_oauth.authorize_button/index.html"
    result = oauth2.authorize_button("Connect with Cognito",scope="openid", pkce="S256", redirect_uri=redirect_uri)
    if result and "token" in result:
        # If authorization successful, save token in session state
        st.session_state.token = result.get("token")
        # Retrieve the Identity Center token
        st.session_state["idc_jwt_token"] = utils.get_iam_oidc_token(st.session_state.token["id_token"])
        st.session_state["idc_jwt_token"]["expires_at"] = datetime.now(tz=UTC) + \
            timedelta(seconds=st.session_state["idc_jwt_token"]["expiresIn"])
        st.rerun()
else:
    token = st.session_state["token"]
    refresh_token = token["refresh_token"] # saving the long lived refresh_token
    user_email = jwt.decode(token["id_token"], options={"verify_signature": False})["email"]
    if st.button("Refresh Cognito Token") :
        # If refresh token button is clicked or the token is expired, refresh the token
        token = oauth2.refresh_token(token, force=True)
        # Put the refresh token in the session state as it is not returned by Cognito
        token["refresh_token"] = refresh_token
        # Retrieve the Identity Center token

        st.session_state.token = token
        st.rerun()

    if "idc_jwt_token" not in st.session_state:
        st.session_state["idc_jwt_token"] = utils.get_iam_oidc_token(token["id_token"])
        st.session_state["idc_jwt_token"]["expires_at"] = datetime.now(UTC) + \
            timedelta(seconds=st.session_state["idc_jwt_token"]["expiresIn"])
    elif st.session_state["idc_jwt_token"]["expires_at"] < datetime.now(UTC):
        # If the Identity Center token is expired, refresh the Identity Center token
        try:
            st.session_state["idc_jwt_token"] = utils.refresh_iam_oidc_token(
                st.session_state["idc_jwt_token"]["refreshToken"]
                )
            st.session_state["idc_jwt_token"]["expires_at"] = datetime.now(UTC) + \
                timedelta(seconds=st.session_state["idc_jwt_token"]["expiresIn"])
        except Exception as e:
            st.error(f"Error refreshing Identity Center token: {e}. Please reload the page.")

    col1, col2 = st.columns([1,1])

    with col1:
        st.write("Welcome: ", user_email)
    with col2:
        st.button("Clear Chat History", on_click=clear_chat_history)

st.write("### Upload File to S3")

# Let the user choose a file to upload
uploaded_file = st.file_uploader("Choose a file to upload")

if uploaded_file:
    # Calculate file size for progress reporting
    file_size = len(uploaded_file.getbuffer())
    progress_bar = st.progress(0)

    # Create a callback class that updates the progress bar
    class ProgressPercentage:
        def __init__(self, total_size):
            self._total_size = total_size
            self._seen_so_far = 0

        def __call__(self, bytes_amount):
            self._seen_so_far += bytes_amount
            percentage = int((self._seen_so_far / self._total_size) * 100)
            progress_bar.progress(min(100, percentage))

    progress = ProgressPercentage(file_size)

    if st.button("Upload File"):
        # Ensure AWS credentials are available.
        if not st.session_state.get("aws_credentials"):
            if "idc_jwt_token" in st.session_state:
                # This call will assume the role and populate st.session_state.aws_credentials
                utils.assume_role_with_token(st.session_state["idc_jwt_token"]["idToken"])
            else:
                st.error("No identity token available. Please log in first.")
                st.stop()
        try:
            # Create the S3 client using the assumed role credentials.
            s3_client = boto3.client(
                's3',
                region_name='us-east-1',
                aws_access_key_id=st.session_state.aws_credentials.get('AccessKeyId'),
                aws_secret_access_key=st.session_state.aws_credentials.get('SecretAccessKey'),
                aws_session_token=st.session_state.aws_credentials.get('SessionToken')
            )
            # Ensure the file pointer is at the beginning
            uploaded_file.seek(0)
            s3_client.upload_fileobj(
                Fileobj=uploaded_file,
                Bucket="luminaitestbucket",
                Key=uploaded_file.name,
                Callback=progress
            )
            st.success("Upload complete!")
        except ClientError as e:
            st.error(f"Error uploading file: {e}")
        except Exception as e:
            st.error(f"Error uploading file: {e}")

    # Initialize the chat messages in the session state if it doesn't exist
    if "messages" not in st.session_state:
        st.session_state["messages"] = [{"role": "assistant", "content": "How can I help you?"}]

    if "conversationId" not in st.session_state:
        st.session_state["conversationId"] = ""

    if "parentMessageId" not in st.session_state:
        st.session_state["parentMessageId"] = ""

    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []

    if "questions" not in st.session_state:
        st.session_state.questions = []

    if "answers" not in st.session_state:
        st.session_state.answers = []

    if "input" not in st.session_state:
        st.session_state.input = ""


    # Display the chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])


    # User-provided prompt
    if prompt := st.chat_input():
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)


    # If the last message is from the user, generate a response from the Q_backend
    if st.session_state.messages[-1]["role"] != "assistant":
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                placeholder = st.empty()
                response = utils.get_queue_chain(prompt,st.session_state["conversationId"],
                                                 st.session_state["parentMessageId"],
                                                 st.session_state["idc_jwt_token"]["idToken"])
                if "references" in response:
                    full_response = f"""{response["answer"]}\n\n---\n{response["references"]}"""
                else:
                    full_response = f"""{response["answer"]}\n\n---\nNo sources"""
                placeholder.markdown(full_response)
                st.session_state["conversationId"] = response["conversationId"]
                st.session_state["parentMessageId"] = response["parentMessageId"]


        st.session_state.messages.append({"role": "assistant", "content": full_response})
        feedback = streamlit_feedback(
            feedback_type="thumbs",
            optional_text_label="[Optional] Please provide an explanation",
        )
