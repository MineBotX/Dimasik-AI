from assistant.brain import train


if __name__ == "__main__":
    vocab, examples = train()
    print(
        f"DimaCore 2.0 training complete. "
        f"Vocabulary: {vocab}; training pairs: {examples}."
    )
