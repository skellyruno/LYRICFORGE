# Optional expressive narration

Kokoro remains the automatic fast narrator. Chatterbox must be selected explicitly. Install the pinned optional runtime separately (Python 3.11, CPU torch/torchaudio 2.6.0 and chatterbox-tts 0.1.6); verify the model using field-notes/inference/expression_live.py. Model revision fcdac3112359983a8dd4a798da91ab87b96006ca. No weights or additional runtime dependencies are bundled.

Set LYRICFORGE_EXPRESSION_PYTHON to the optional environment's python executable and LYRICFORGE_EXPRESSION_MODEL to the verified model directory before launch. The worker uses its built-in voice only, disables Hugging Face network access and requires a tensor-only conditional loader.

Chapter prefixes [reveal], [detail], [compare], [close], [steady] direct the neural model without changing captions. Pronunciation substitutions affect spoken audio only. The explicit global speed slider applies pitch-preserving time stretch; chapter direction does not double-stretch the voice.

CPU latency is substantial (earlier controlled auditions took 25–36 seconds per short phrase). Up to 60 phrases and a bounded, cancellable one-hour process. Use Kokoro for fast iterations. Review expression and pronunciation before publishing.
