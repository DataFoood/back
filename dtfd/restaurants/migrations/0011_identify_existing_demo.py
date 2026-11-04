from django.db import migrations


SEEDS = [('canto-da-serra', 'Canto da Serra', 'Churrasco e frango caipira em ambiente familiar, amplo e sem pressa. Referência em Marília para quem busca comida caseira bem feita: o frango caipira assado na brasa é o carro-chefe, servido com arroz, feijão tropeiro e couve. Almoço executivo durante a semana com prato feito por preço fixo.'), ('mr-beer-marilia', 'Mr. Beer Marília', 'Happy hour com chopps gelados e petiscos fartos no centro. Ponto de encontro para uma roda de amigos ou confraternizações; aos fins de semana tem música ao vivo e o salão enche cedo.'), ('dallas-restaurante', 'Dallas Restaurante', 'Jantar em ambiente sofisticado, a melhor opção para ocasiões especiais em Marília. Iluminação baixa, mesas bem espaçadas e serviço atento. Cortes nobres, massas artesanais e a carta de vinhos mais completa da cidade.'), ('ki-sushi-marilia', 'Ki Sushi', 'Rodízio de sushi e temaki bem avaliado, popular entre universitários. Grande variedade de peças, temakis e pratos quentes por preço acessível. Ambiente animado e serviço ágil; reserva aconselhada nos fins de semana.'), ('pizza-del-rei', 'Pizza Del Rei', 'Pizzaria tradicional com massa fina e forno a lenha, há mais de 20 anos em Marília. Ambiente familiar e tranquilo, com entrega para boa parte da cidade. A pizza doce de banana com canela tem fila de fãs.'), ('cafe-oficina', 'Café Oficina', 'Café especial e brunch em ambiente descolado, decorado com peças de oficina mecânica. Wi-fi estável, tomadas em todas as mesas — o lugar favorito para trabalhar fora de casa. O flat white e o croissant são os mais pedidos.'), ('espeto-do-alemao', 'Espeto do Alemão', 'Espetinhos na brasa em ambiente aberto e informal, ponto de encontro do Jardim Europa aos fins de semana. Carne, frango, coração e queijo coalho feitos na hora, com pão de alho e vinagrete. Sem reserva: chegue cedo.'), ('laguna-restaurante', 'Laguna Restaurante', 'Frutos do mar frescos com vista para a represa — o jantar romântico mais especial de Marília. Janelas que enquadram a água, iluminação baixa e música suave. Destaques: moqueca de camarão e polvo grelhado.'), ('chopperia-marilia', 'Chopperia Marília', 'Chopps artesanais e tábuas fartíssimas: um dos bares mais movimentados da cidade, sempre com 4 torneiras diferentes. Ambiente animado, com música ao vivo às sextas e sábados.')]


def mark_demo(apps, schema_editor):
    Restaurant = apps.get_model('restaurants', 'Restaurant')
    for slug, name, description in SEEDS:
        Restaurant.objects.filter(slug=slug, name=name, description=description, origin='manual').update(is_demo=True)


class Migration(migrations.Migration):
    dependencies = [('restaurants', '0010_catalogimport_restaurant_is_demo_and_more')]
    operations = [migrations.RunPython(mark_demo, migrations.RunPython.noop)]
