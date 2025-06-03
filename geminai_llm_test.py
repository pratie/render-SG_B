from google import genai

client = genai.Client(api_key="")

# print("Available models:")
# for model in client.models.list():
#     print(model.name)


response = client.models.generate_content(
    model="gemini-2.5-flash-preview-04-17-thinking",
    contents="give me a comment to post on r/saas sub post is about lead gen, i want to sublty prompt my lead gen tool- SneakyguyAI",
)

print(response.text)