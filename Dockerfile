FROM postgres:14-alpine

# Add initialization scripts
COPY init.sql /docker-entrypoint-initdb.d/

# Set environment variables
ENV POSTGRES_USER=postgres
ENV POSTGRES_PASSWORD=postgres
ENV POSTGRES_DB=pqfile_db

# Expose the PostgreSQL port
EXPOSE 5432
