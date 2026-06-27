import asyncio

import edge_tts

async def test():
    ssml = (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"'
        ' xmlns:mstts="http://www.w3.org/2001/mstts">'
        '<voice name="en-GB-RyanNeural">'
        '<mstts:express-as style="cheerful">'
        "Hey Yan, I'm doing great!"
        '</mstts:express-as></voice></speak>'
    )
    print(f"SSML: {ssml[:100]}...")
    c = edge_tts.Communicate(ssml, "en-GB-RyanNeural")
    count = 0
    async for chunk in c.stream():
        if chunk["type"] == "audio":
            count += len(chunk["data"])
    print(f"Audio generated: {count} bytes")

asyncio.run(test())
