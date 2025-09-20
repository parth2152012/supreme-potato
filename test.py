import streamlit as st
from transformers import pipeline

# Use st.cache_resource to cache models for performance
@st.cache_resource
def get_sentiment_analyzer():
    return pipeline("sentiment-analysis")

@st.cache_resource
def get_text_generator():
    # Load a pre-trained text generation model (gpt2 is a good, fast choice)
    return pipeline("text-generation", model="gpt2")

# Get the cached models
sentiment_analyzer = get_sentiment_analyzer()
text_generator = get_text_generator()

# Set page config for a polished look
st.set_page_config(
    page_title="Youth Brand AI Assistant",
    page_icon="✨",
    layout="wide"
)

# Custom CSS for a sleek, modern look
st.markdown("""
    <style>
    .stButton>button {
        width: 100%;
        background-color: #FF4B4B;
        color: white;
    }
    .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
        font-size: 1.2rem;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 5px;
    }
    </style>
""", unsafe_allow_html=True)

st.title("✨ AI Marketing Assistant for Youth Brands")
st.markdown("A powerful tool for creating and analyzing content that resonates with a young audience.")
st.divider()

# --- Brand Profile Setup (remains in the sidebar) ---
st.sidebar.header("Brand Profile")
brand_name = st.sidebar.text_input("Brand Name", placeholder="e.g., ChillThreads")
brand_niche = st.sidebar.text_input("Brand Niche", placeholder="e.g., sustainable streetwear")
target_audience = st.sidebar.text_input("Target Audience", placeholder="e.g., Gen Z (ages 16-24)")
brand_tone = st.sidebar.text_input("Brand Tone", placeholder="e.g., fun, casual, authentic")

# --- Tabbed Interface for Polished UI ---
tab1, tab2, tab3, tab4 = st.tabs(["💡 Content Ideas", "📝 Chat Assistant", "🔍 Sentiment Analysis", "📈 Business Growth"])

# --- Tab 1: Content Ideas ---
with tab1:
    st.header("Brainstorm Fresh Ideas")
    st.markdown("Instantly generate new content ideas based on your brand profile.")
    
    if st.button("Generate Ideas", key="generate_ideas_btn"):
        if brand_name and brand_niche and target_audience and brand_tone:
            with st.spinner('Brainstorming ideas...'):
                idea_prompt = f"As an expert in marketing to {target_audience}, generate 5 creative content ideas for {brand_name}, a brand specializing in {brand_niche}. The brand's tone is {brand_tone}. The ideas should be suitable for a viral social media campaign."
                
                # Updated text generation with anti-repetition parameters
                generated_ideas = text_generator(
                    idea_prompt,
                    max_length=500,
                    num_return_sequences=1,
                    do_sample=True,
                    repetition_penalty=1.5,
                    top_k=50,
                    temperature=0.8
                )[0]['generated_text']
                
                st.subheader("Fresh Content Ideas:")
                st.info(generated_ideas.strip())
        else:
            st.warning("Please fill out the Brand Profile in the sidebar to generate ideas!")

# --- Tab 2: Chat Assistant ---
with tab2:
    st.header("Chat with Your Assistant")
    st.markdown("Ask questions and get creative content and marketing advice.")
    
    # Initialize chat history in session state
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Display chat messages from history on app rerun
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Accept user input
    if prompt := st.chat_input("What content do you need?"):
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": prompt})
        # Display user message in chat message container
        with st.chat_message("user"):
            st.markdown(prompt)

        # Generate assistant's response
        with st.chat_message("assistant"):
            with st.spinner("Generating..."):
                # Pass the full context of the conversation to the model
                full_context = " ".join([m["content"] for m in st.session_state.messages])
                
                response = text_generator(
                    full_context,
                    max_length=len(full_context) + 200, # Increased max_length to allow for new content
                    num_return_sequences=1,
                    do_sample=True,
                    repetition_penalty=1.5,
                    top_k=50,
                    temperature=0.8
                )[0]['generated_text']
                
                # Extract only the new part of the response by removing the prompt
                new_response = response.strip().replace(full_context.strip(), "").strip()
                st.markdown(new_response)

        # Add assistant response to chat history
        st.session_state.messages.append({"role": "assistant", "content": new_response})

# --- Tab 3: Sentiment Analysis ---
with tab3:
    st.header("Analyze User Sentiment")
    st.markdown("Determine the sentiment of any text, like a product review or social media comment.")
    sentiment_text_input = st.text_area("Enter text to analyze:", height=150, placeholder="Example: 'This new product is so legit, I'm obsessed!'")

    if st.button("Analyze Sentiment", key="analyze_sentiment_btn"):
        if sentiment_text_input:
            with st.spinner('Analyzing...'):
                result = sentiment_analyzer(sentiment_text_input)[0]
                label = result['label']
                score = result['score']
                
                st.subheader("Analysis Results:")
                if label == "POSITIVE":
                    st.success(f"Positive! 🎉 (Confidence: {score:.2f})")
                elif label == "NEGATIVE":
                    st.error(f"Negative 😞 (Confidence: {score:.2f})")
                else:
                    st.info(f"Neutral 😐 (Confidence: {score:.2f})")
        else:
            st.warning("Please enter some text to analyze.")

# --- Tab 4: Business Growth ---
with tab4:
    st.header("Business Growth Strategy")
    st.markdown("Get tailored advice on how to grow your brand's reach and impact.")
    
    growth_question = st.text_area("What would you like to know about growing your business?", height=100, placeholder="Example: 'What are some effective ways to use social media influencers to grow my brand?'")

    if st.button("Get Advice", key="get_advice_btn"):
        if growth_question and brand_name and brand_niche and target_audience and brand_tone:
            with st.spinner('Generating advice...'):
                advice_prompt = f"As a marketing expert for {brand_name}, a brand for {target_audience} in the {brand_niche} niche with a {brand_tone} tone, provide a detailed answer to the following question: {growth_question}. Be specific and actionable."
                
                # Updated text generation with anti-repetition parameters
                generated_advice = text_generator(
                    advice_prompt,
                    max_length=700,
                    num_return_sequences=1,
                    do_sample=True,
                    repetition_penalty=1.5,
                    top_k=50,
                    temperature=0.8
                )[0]['generated_text']
                
                st.subheader("Actionable Growth Advice:")
                st.info(generated_advice.strip())
        else:
            st.warning("Please fill out both the Brand Profile and your question to get advice.")