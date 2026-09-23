import pytest

from app.ws.hub import Hub


class FauxSocket:
    def __init__(self):
        self.recus = []

    async def send_json(self, donnees):
        self.recus.append(donnees)


@pytest.mark.asyncio
async def test_diffuse_aux_abonnes_de_la_session():
    hub = Hub()
    a, b, autre = FauxSocket(), FauxSocket(), FauxSocket()
    hub.rejoindre(1, a)
    hub.rejoindre(1, b)
    hub.rejoindre(2, autre)

    await hub.diffuser(1, {"type": "notice", "payload": {"level": "info", "message": "ok"}})

    assert len(a.recus) == 1
    assert len(b.recus) == 1
    assert autre.recus == []


@pytest.mark.asyncio
async def test_un_socket_mort_ne_bloque_pas_les_autres():
    class SocketMort(FauxSocket):
        async def send_json(self, donnees):
            raise RuntimeError("ferme")

    hub = Hub()
    mort, vivant = SocketMort(), FauxSocket()
    hub.rejoindre(1, mort)
    hub.rejoindre(1, vivant)

    await hub.diffuser(1, {"type": "notice", "payload": {}})

    assert len(vivant.recus) == 1
    assert mort not in hub._salles[1]
