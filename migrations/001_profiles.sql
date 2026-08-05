-- migrations/001_profiles.sql
--
-- Correr una sola vez en el SQL Editor del proyecto de Supabase
-- (Dashboard > SQL Editor > New query), DESPUÉS de crear el proyecto
-- y ANTES de invitar al primer usuario.
--
-- Un solo proyecto de Supabase para todo el ecosistema (Lattise Studio
-- + Simulador_IO): una fila de `profiles` por usuario, válida para
-- ambas apps.
--
-- Diseño: esta tabla existe desde HOY, pero `plan` no bloquea a nadie
-- todavía — `auth_gate.require_plan()` en ambos repos es un stub que
-- hoy equivale a `require_auth()`. El día que se active el paywall
-- real, se cambia el cuerpo de `require_plan()` para leer esta
-- columna, sin tocar el resto de la app.

create table if not exists public.profiles (
    id         uuid primary key references auth.users(id) on delete cascade,
    email      text not null,
    plan       text not null default 'beta',  -- 'beta' | 'paid' | 'suspended' (valores futuros)
    created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

-- Cada usuario solo puede leer su propia fila (necesario para que el
-- gate pueda consultar `plan` desde el anon key sin exponer la tabla
-- completa).
create policy "profiles_select_own"
    on public.profiles for select
    using (auth.uid() = id);

-- Trigger: al crear un usuario en auth.users (invitación manual desde
-- el dashboard), se crea automáticamente su fila en profiles con
-- plan='beta'. Así nunca hay que acordarse de insertar la fila a mano.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
    insert into public.profiles (id, email)
    values (new.id, new.email);
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute procedure public.handle_new_user();
