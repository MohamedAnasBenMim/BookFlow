-- Rôle applicatif NON superutilisateur : un superutilisateur contourne le Row-Level Security.
CREATE ROLE bookflow LOGIN PASSWORD 'bookflow' NOSUPERUSER NOCREATEROLE;
CREATE DATABASE bookflow OWNER bookflow;
CREATE DATABASE bookflow_test OWNER bookflow;
