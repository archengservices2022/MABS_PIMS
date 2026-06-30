#!/bin/bash
# Script to update date displays to MM-DD-YYYY format using format_date filter

# List of date fields to update
# Pattern: replace {{ variable.get('date_field') }} with {{ variable.get('date_field') | format_date }}

for file in e:/MABS_PIMS/web_app/templates/*.html; do
  echo "Processing $(basename $file)..."
  
  # Replace date displays with format_date filter
  sed -i "s/{{ r\.get('date','\([^']*\)') }}/{{ r.get('date','\1') | format_date }}/g" "$file"
  sed -i "s/{{ p\.get('start_date','\([^']*\)') }}/{{ p.get('start_date','\1') | format_date }}/g" "$file"
  sed -i "s/{{ p\.get('date','\([^']*\)') }}/{{ p.get('date','\1') | format_date }}/g" "$file"
  sed -i "s/{{ meta\.get('due_date','\([^']*\)') }}/{{ meta.get('due_date','\1') | format_date }}/g" "$file"
  sed -i "s/{{ project\.get('start_date','\([^']*\)') }}/{{ project.get('start_date','\1') | format_date }}/g" "$file"
  sed -i "s/{{ project\.get('end_date','\([^']*\)') }}/{{ project.get('end_date','\1') | format_date }}/g" "$file"
  sed -i "s/{{ project\.get('date_received','\([^']*\)') }}/{{ project.get('date_received','\1') | format_date }}/g" "$file"
  sed -i "s/{{ project\.get('date_received') }}/{{ project.get('date_received') | format_date }}/g" "$file"
  sed -i "s/{{ exp\.get('date','\([^']*\)') }}/{{ exp.get('date','\1') | format_date }}/g" "$file"
  sed -i "s/{{ q\.get('date','\([^']*\)') }}/{{ q.get('date','\1') | format_date }}/g" "$file"
  sed -i "s/{{ quote\.get('date','\([^']*\)') }}/{{ quote.get('date','\1') | format_date }}/g" "$file"
  sed -i "s/{{ payment\.get('date','\([^']*\)') }}/{{ payment.get('date','\1') | format_date }}/g" "$file"
  sed -i "s/{{ co\.get('created_at','\([^']*\)') }}\[:10\]/{{ co.get('created_at','\1') | format_date }}/g" "$file"
done

echo "Done!"
