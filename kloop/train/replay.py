"""Deterministic general arithmetic, language and instruction replay examples."""


def rows(batch, count, *, offset=0, repair=0):
    result = []
    for index in range(offset, offset + count):
        number = batch * 10000 + repair * 1000 + index
        if index % 3 == 0:
            left, right = number % 97 + 2, number // 97 + 3
            question, answer = f"What is {left} plus {right}?", str(left + right)
        elif index % 3 == 1:
            question = f"Convert this text to lowercase: Cedar Grove {number}"
            answer = f"cedar grove {number}"
        else:
            question = (
                "Return only the final item of this comma-separated list: "
                f"alpha, beta, item{number}"
            )
            answer = f"item{number}"
        result.append(
            {"question": question, "answer": answer, "kind": "replay", "source_item_ids": []}
        )
    return result
