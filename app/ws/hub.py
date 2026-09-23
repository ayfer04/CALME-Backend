"""Registre des connexions temps reel, une salle par seance.

Un socket qui tombe ne doit jamais empecher les autres de recevoir : c'est
tout l'interet d'avoir une diffusion tolerante plutot qu'une boucle naive.
"""

from collections import defaultdict


class Hub:
    def __init__(self) -> None:
        self._salles: dict[int, set] = defaultdict(set)

    def rejoindre(self, session_id: int, socket) -> None:
        self._salles[session_id].add(socket)

    def quitter(self, session_id: int, socket) -> None:
        self._salles[session_id].discard(socket)

    async def diffuser(self, session_id: int, evenement: dict) -> None:
        morts = []
        for socket in list(self._salles.get(session_id, ())):
            try:
                await socket.send_json(evenement)
            except Exception:
                morts.append(socket)
        for socket in morts:
            self._salles[session_id].discard(socket)


hub = Hub()
